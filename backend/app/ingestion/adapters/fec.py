"""OpenFEC candidate filings -> upcoming federal contests and candidacies.

A filing with the FEC is NOT ballot qualification. Candidacies loaded here carry status
`filed_with_fec`; ballot status must come from state election officials.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime

import httpx

from ...config import get_settings
from ...countries.us import UnitedStatesAdapter, federal_general_election_date
from ...models import Source
from ..framework import (
    FetchedFile,
    Issue,
    RunContext,
    SourceAdapter,
    SourceUnavailable,
    StructuralError,
    TransientSourceError,
    register,
)
from ..loaders import Resolver

BASE = "https://api.open.fec.gov/v1/candidates/"
CAND_ID = re.compile(r"^[HSP][0-9A-Z]{8}$")
US = UnitedStatesAdapter()


def senate_class_for_year(year: int) -> int:
    """Regular Senate elections: class 1 in 2024/2030..., class 2 in 2026, class 3 in 2028."""
    return {2: 1, 4: 2, 0: 3}[year % 6]


class FecCandidatesAdapter(SourceAdapter):
    key = "us_fec_candidates"
    version = "1.0.0"
    schema_version = "openfec-v1-candidates"

    def fetch(self, source: Source, params: dict) -> list[FetchedFile]:
        key = get_settings().fec_api_key
        if not key:
            raise SourceUnavailable("ELECTION_FEC_API_KEY is not configured. " + source.remediation)
        year, office = int(params["election_year"]), params.get("office", "H")
        files, page, pages = [], 1, 1
        with httpx.Client(timeout=30) as client:
            while page <= pages:
                q = {
                    "election_year": year,
                    "office": office,
                    "per_page": 100,
                    "page": page,
                    "api_key": key,
                    "sort": "name",
                }
                if params.get("state"):
                    q["state"] = params["state"]
                try:
                    resp = client.get(BASE, params=q)
                except httpx.HTTPError as exc:
                    raise TransientSourceError(f"OpenFEC request failed: {exc}") from exc
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise TransientSourceError(f"OpenFEC HTTP {resp.status_code}")
                if resp.status_code in (401, 403):
                    raise SourceUnavailable(f"OpenFEC rejected the API key (HTTP {resp.status_code})")
                resp.raise_for_status()
                body = resp.json()
                pages = int(body.get("pagination", {}).get("pages", 1))
                public_url = str(resp.url).replace(key, "REDACTED")  # never persist secrets in provenance
                files.append(
                    FetchedFile(
                        public_url,
                        resp.content.replace(key.encode(), b"REDACTED"),
                        "application/json",
                        datetime.now(UTC),
                        {"status": resp.status_code, "page": page},
                        f"fec-{office}-{year}-p{page}.json",
                    )
                )
                page += 1
                time.sleep(0.7)  # stay well under per-key rate limits
        return files

    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        year = int(ctx.params["election_year"])
        r = Resolver(ctx, "US")
        edate = federal_general_election_date(year)
        expected_class = senate_class_for_year(year)
        for f in files:
            try:
                body = json.loads(f.content)
                results = body["results"]
            except (ValueError, KeyError) as exc:
                raise StructuralError(
                    [Issue(f.filename or f.url, "schema", f"not an OpenFEC page: {exc}", blocking=True)]
                ) from exc
            for n, c in enumerate(results):
                ref = f"{f.filename} result {n}"
                cid = c.get("candidate_id", "")
                if not CAND_ID.match(cid):
                    ctx.quarantine(Issue(ref, "identifier", f"malformed FEC candidate_id {cid!r}"))
                    continue
                if year not in (c.get("election_years") or []):
                    ctx.count("skipped_other_years")
                    continue
                office_code, state = c.get("office"), c.get("state")
                unit = r.unit(state or "")
                if unit is None:
                    ctx.quarantine(Issue(ref, "geo_join", f"unknown state {state!r} for {cid}"))
                    continue
                election = r.election(
                    year, "general", edate, unit.timezone or "America/New_York", "2 U.S.C. 7 (derived by rule)"
                )
                if office_code == "H":
                    seats = unit_seats(r, unit)
                    try:
                        dnum = int(c.get("district") or 0)
                    except ValueError:
                        ctx.quarantine(Issue(ref, "district", f"non-numeric district {c.get('district')!r}"))
                        continue
                    if seats == 0:
                        office = r.office("us_house_delegate")
                        contest = r.contest(
                            election, office, f"Delegate {unit.abbreviation} ({year})", "fptp", unit=unit
                        )
                    else:
                        # 2020 apportionment governs 2022-2030 elections only.
                        in_range = (dnum in (0, 1)) if seats == 1 else (1 <= dnum <= seats)
                        if 2022 <= year <= 2030 and not in_range:
                            ctx.quarantine(
                                Issue(
                                    ref,
                                    "district_range",
                                    f"{state}-{dnum} outside 1..{seats} (2020 apportionment)",
                                    suggested_action="Check the FEC record; may be a data entry error.",
                                )
                            )
                            continue
                        code = f"{state}-AL" if seats == 1 else f"{state}-{dnum:02d}"
                        office = r.office("us_house")
                        plan = r.plan_as_contested(office, unit, year)
                        dist = r.district(
                            plan, code, f"{unit.name} {'at-large' if seats == 1 else f'district {dnum}'}", unit
                        )
                        contest = r.contest(
                            election,
                            office,
                            f"U.S. House {code} ({year})",
                            US.system_for("us_house", unit.code, "general"),
                            district=dist,
                            unit=unit,
                        )
                elif office_code == "S":
                    classes = unit_classes(r, unit)
                    if expected_class not in classes:
                        ctx.quarantine(
                            Issue(
                                ref,
                                "senate_special_unconfirmed",
                                f"{state} has no class {expected_class} seat in {year}; filing may be "
                                "for a special election",
                                severity="warning",
                                suggested_action="Confirm via the editorial calendar (with citation).",
                            )
                        )
                    office = r.office("us_senate")
                    contest = r.contest(
                        election,
                        office,
                        f"U.S. Senate {state} ({year})",
                        US.system_for("us_senate", unit.code, "general"),
                        unit=unit,
                    )
                else:
                    ctx.count("skipped_office")
                    continue
                party = r.party(c.get("party") or c.get("party_full"), ref)
                cand = r.candidate(c.get("name") or cid, unit, {"fec": cid})
                r.candidacy(
                    contest,
                    cand,
                    c.get("name") or cid,
                    party,
                    incumbent=(c.get("incumbent_challenge") == "I"),
                    status="filed_with_fec",
                )
                ctx.count("filings")
        ctx.check("fec_pages", True, f"{len(files)} page(s)")


def _attrs(r: Resolver, unit) -> dict:  # type: ignore[no-untyped-def]
    from ...countries.us import load_states  # noqa: PLC0415

    key = ("state_attrs",)
    if key not in r._cache:
        r._cache[key] = {s["fips"]: s for s in load_states()}
    return r._cache[key][unit.code]  # type: ignore[index]


def unit_seats(r: Resolver, unit) -> int:  # type: ignore[no-untyped-def]
    return int(_attrs(r, unit)["house_seats_2020"])


def unit_classes(r: Resolver, unit) -> set[int]:  # type: ignore[no-untyped-def]
    return {int(c) for c in _attrs(r, unit)["senate_classes"].split("|") if c}


register(FecCandidatesAdapter())
