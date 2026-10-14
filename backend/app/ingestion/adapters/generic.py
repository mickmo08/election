"""Country-agnostic normalized formats: official results, editorial contest calendar, polls.

Formats are specified in docs/adapters/normalized-formats.md. State- or country-specific
publisher formats are mapped into these by small, separately tested mappers.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ...countries.registry import get_adapter
from ...models import ELECTION_KINDS, Poll, PollQuestion, PollResult, Pollster
from ..framework import FetchedFile, Issue, RunContext, SourceAdapter, StructuralError, register
from ..loaders import Resolver, normalize_label
from ..results_writer import Line, write_snapshot
from ..validation import parse_bool, parse_date, parse_datetime, parse_float, parse_int, read_csv


def _contest_for(ctx: RunContext, r: Resolver, row: dict, ref: str, year: int, edate: date, kind: str):  # type: ignore[no-untyped-def]
    adapter = get_adapter(r.country)
    unit = r.unit(row["admin_unit"]) if row.get("admin_unit") else None
    if row.get("admin_unit") and unit is None:
        ctx.quarantine(Issue(ref, "geo_join", f"unknown admin unit {row['admin_unit']!r}"))
        return None
    try:
        office = r.office(row["office_key"])
    except KeyError:
        ctx.quarantine(Issue(ref, "office_unknown", f"unknown office {row['office_key']!r} for {r.country}"))
        return None
    stage = "primary" if "primary" in kind else ("runoff" if "runoff" in kind else "general")
    system = adapter.system_for(office.key, unit.code if unit else None, stage)
    election = r.election(
        year,
        kind,
        edate,
        (unit.timezone if unit else None) or adapter.default_timezone,
        row.get("citation_url") or f"source: {ctx.source.key}",
        unit if kind != "general" else None,
    )
    party = r.party(row.get("primary_party"), ref) if row.get("primary_party") else None
    seats = int(row.get("seats") or 1)
    is_special = parse_bool(row.get("is_special", "")) or kind.startswith("special")
    seat_class = row.get("seat_class") or None
    label = f"{office.name}"
    if office.districted and row.get("district"):
        if unit is None:
            ctx.quarantine(Issue(ref, "geo_join", "districted office requires admin_unit"))
            return None
        plan = r.plan_as_contested(office, unit, year)
        dist = r.district(plan, row["district"], row.get("district_name") or row["district"], unit, seats)
        label = f"{office.name} {row['district']}"
        return r.contest(
            election,
            office,
            f"{label} ({year}{', ' + kind if kind != 'general' else ''})",
            system,
            district=dist,
            unit=unit,
            party=party,
            seats=seats,
            is_special=is_special,
            seat_class=seat_class,
        )
    name = row.get("contest_name") or f"{office.name} {unit.name if unit else ''}".strip()
    return r.contest(
        election,
        office,
        f"{name} ({year}{', ' + kind if kind != 'general' else ''})",
        system,
        unit=unit,
        party=party,
        seats=seats,
        is_special=is_special,
        seat_class=seat_class,
    )


class EditorialContestsAdapter(SourceAdapter):
    """Curated contest calendar. Every row must cite an official source."""

    key = "editorial_contests_csv"
    version = "1.0.0"
    schema_version = "editorial-contests-v1"
    REQUIRED = ("country", "election_kind", "election_date", "admin_unit", "office_key", "citation_url", "verified_by")

    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        for f in files:
            rows = read_csv(f.content, self.REQUIRED, f.filename or f.url)
            for i, row in enumerate(rows, start=2):
                ref = f"{f.filename} row {i}"
                issues: list[Issue] = []
                if not row["citation_url"].startswith("https://"):
                    ctx.quarantine(
                        Issue(ref, "citation_required", "citation_url must be an https URL to an " "official source")
                    )
                    continue
                if not row["verified_by"]:
                    ctx.quarantine(Issue(ref, "verifier_required", "verified_by is required"))
                    continue
                if row["election_kind"] not in ELECTION_KINDS:
                    ctx.quarantine(Issue(ref, "kind", f"election_kind must be one of {ELECTION_KINDS}"))
                    continue
                edate = parse_date(row["election_date"], "election_date", ref, issues)
                if edate is None:
                    ctx.issues.extend(issues)
                    continue
                r = Resolver(ctx, row["country"])
                if _contest_for(ctx, r, row, ref, edate.year, edate, row["election_kind"]) is not None:
                    ctx.count("contests_upserted")


class OfficialResultsAdapter(SourceAdapter):
    """Normalized official results (one file = one publication of one or more contests)."""

    key = "official_results_csv"
    version = "1.0.0"
    schema_version = "official-results-v1"
    REQUIRED = (
        "country",
        "election_kind",
        "election_date",
        "admin_unit",
        "office_key",
        "district",
        "candidate",
        "party",
        "votes",
        "status",
        "source_as_of",
        "reporting_pct",
    )

    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        for f in files:
            rows = read_csv(f.content, self.REQUIRED, f.filename or f.url)
            raw = ctx.raw_file_for(f)
            groups: dict[tuple, list[tuple[int, dict]]] = defaultdict(list)
            for i, row in enumerate(rows, start=2):
                groups[
                    (
                        row["country"],
                        row["election_kind"],
                        row["election_date"],
                        row["admin_unit"],
                        row["office_key"],
                        row["district"],
                        row.get("primary_party", ""),
                    )
                ].append((i, row))
            for items in groups.values():
                ref = f"{f.filename} rows {items[0][0]}-{items[-1][0]}"
                issues: list[Issue] = []
                first = items[0][1]
                adapter = get_adapter(first["country"])
                try:
                    status = adapter.normalize_status(first["status"])
                except ValueError as exc:
                    ctx.quarantine(
                        Issue(
                            ref,
                            "status",
                            str(exc),
                            suggested_action="Add the label to the country " "adapter's status map.",
                        )
                    )
                    continue
                if len({row["status"] for _, row in items}) > 1:
                    ctx.quarantine(Issue(ref, "status", "rows of one contest carry different statuses"))
                    continue
                edate = parse_date(first["election_date"], "election_date", ref, issues)
                as_of = parse_datetime(first["source_as_of"], "source_as_of", ref, issues)
                supported = first["reporting_pct"] != ""
                pct = parse_float(first["reporting_pct"], "reporting_pct", ref, issues, 0, 100) if supported else None
                if edate is None or issues:
                    ctx.issues.extend(issues)
                    continue
                r = Resolver(ctx, first["country"])
                contest = _contest_for(ctx, r, first, ref, edate.year, edate, first["election_kind"])
                if contest is None:
                    continue
                unit = r.unit(first["admin_unit"]) if first["admin_unit"] else None
                lines, seen = [], set()
                for i, row in items:
                    rref = f"{f.filename} row {i}"
                    votes = parse_int(row["votes"], "votes", rref, issues)
                    if votes is None:
                        continue
                    nk = normalize_label(row["candidate"])
                    if nk in seen:
                        issues.append(Issue(rref, "duplicate", f"candidate {row['candidate']!r} listed twice"))
                        continue
                    seen.add(nk)
                    writein = parse_bool(row.get("writein", ""))
                    party = r.party(row["party"], rref) if row["party"] else None
                    cy = None
                    if not writein:
                        ext = {"source_candidate_id": row.get("external_candidate_id")}
                        cand = r.candidate(row["candidate"], unit, ext if ext["source_candidate_id"] else None)
                        cy = r.candidacy(contest, cand, row["candidate"], party, status="on_ballot")
                    lines.append(Line(row["candidate"], votes, row["party"] or None, cy, writein))
                if issues:  # any bad row invalidates the contest's snapshot (partial totals are misleading)
                    ctx.issues.extend(issues)
                    continue
                write_snapshot(
                    ctx,
                    contest,
                    status=status,
                    lines=lines,
                    retrieved_at=f.retrieved_at,
                    raw_file_id=raw.id,
                    record_ref=ref,
                    source_as_of=as_of,
                    reporting_pct=pct,
                    reporting_supported=supported,
                    correction_note=first.get("correction_note") or None,
                )


POPULATIONS = {
    "a": "a",
    "adults": "a",
    "rv": "rv",
    "registered voters": "rv",
    "lv": "lv",
    "likely voters": "lv",
    "v": "v",
    "voters": "v",
}
SAMPLING = ("probability", "nonprobability", "mixed", "unknown")


class PollsAdapter(SourceAdapter):
    key = "polls_csv"
    version = "1.0.0"
    schema_version = "polls-v1"
    REQUIRED = (
        "pollster",
        "country",
        "question_scope",
        "field_start",
        "field_end",
        "population",
        "sample_size",
        "mode",
        "sampling_method",
        "methodology_url",
        "question_wording",
        "choice",
        "pct",
    )

    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        tenant_id = ctx.params.get("tenant_id")
        for f in files:
            rows = read_csv(f.content, self.REQUIRED, f.filename or f.url)
            raw = ctx.raw_file_for(f)
            polls: dict[tuple, list[tuple[int, dict]]] = defaultdict(list)
            for i, row in enumerate(rows, start=2):
                k = (
                    row["pollster"],
                    row.get("sponsor", ""),
                    row["field_start"],
                    row["field_end"],
                    row["population"].lower(),
                    row.get("admin_unit", ""),
                    row.get("office_key", ""),
                    row.get("district", ""),
                    row["question_scope"],
                )
                polls[k].append((i, row))
            for items in polls.values():
                self._load_poll(ctx, f, raw.id, items, tenant_id)

    def _load_poll(self, ctx: RunContext, f: FetchedFile, raw_id, items: list[tuple[int, dict]], tenant_id) -> None:  # type: ignore[no-untyped-def]
        ref = f"{f.filename} rows {items[0][0]}-{items[-1][0]}"
        first = items[0][1]
        issues: list[Issue] = []
        start = parse_date(first["field_start"], "field_start", ref, issues)
        end = parse_date(first["field_end"], "field_end", ref, issues)
        pop = POPULATIONS.get(first["population"].lower())
        if pop is None:
            issues.append(Issue(ref, "population", f"population {first['population']!r} not in a/rv/lv/v"))
        sampling = first["sampling_method"].lower()
        if sampling not in SAMPLING:
            issues.append(Issue(ref, "sampling", f"sampling_method must be one of {SAMPLING}"))
        n = parse_int(first["sample_size"], "sample_size", ref, issues, minimum=1)
        if not first["methodology_url"].startswith("https://"):
            issues.append(Issue(ref, "methodology_required", "methodology_url (https) is required"))
        moe = parse_float(first.get("published_moe", ""), "published_moe", ref, issues, 0, 50)
        if start and end and end < start:
            issues.append(Issue(ref, "field_dates", "field_end precedes field_start"))
        if issues:
            ctx.issues.extend(issues)
            return
        if moe is not None and sampling == "nonprobability":
            ctx.quarantine(
                Issue(
                    ref,
                    "moe_nonprobability",
                    "pollster published a margin of error for a "
                    "nonprobability sample; stored as published but not displayed as a sampling MOE",
                    severity="warning",
                )
            )
        r = Resolver(ctx, first["country"])
        contest = None
        if first["question_scope"] == "contest":
            edate = parse_date(first.get("election_date", ""), "election_date", ref, issues)
            if edate is None:
                ctx.issues.extend(issues)
                return
            contest = _contest_for(ctx, r, first, ref, edate.year, edate, first.get("election_kind") or "general")
            if contest is None:
                return
        pollster = ctx.db.query(Pollster).filter_by(name=first["pollster"]).one_or_none()
        if pollster is None:
            pollster = Pollster(name=first["pollster"])
            ctx.db.add(pollster)
            ctx.db.flush()
        unit = r.unit(first["admin_unit"]) if first.get("admin_unit") else None
        poll = Poll(
            tenant_id=tenant_id,
            pollster_id=pollster.id,
            sponsor=first.get("sponsor") or None,
            sponsor_is_partisan=parse_bool(first.get("sponsor_is_partisan", "")),
            country_code=first["country"],
            admin_unit_id=unit.id if unit else None,
            contest_id=contest.id if contest else None,
            question_scope=first["question_scope"],
            field_start=start,
            field_end=end,
            population=pop,
            sample_size=n,
            mode=first["mode"],
            sampling_method=sampling,
            weighting=first.get("weighting", ""),
            methodology_url=first["methodology_url"],
            questionnaire_url=first.get("questionnaire_url") or None,
            published_moe=moe,
            tracking_series=first.get("tracking_series") or None,
            source_id=ctx.source.id,
            raw_file_id=raw_id,
        )
        ctx.db.add(poll)
        ctx.db.flush()
        questions: dict[str, PollQuestion] = {}
        totals: dict[tuple, float] = defaultdict(float)
        for i, row in items:
            q = questions.get(row["question_wording"])
            if q is None:
                q = PollQuestion(poll_id=poll.id, wording=row["question_wording"], topic=row.get("topic") or None)
                ctx.db.add(q)
                ctx.db.flush()
                questions[row["question_wording"]] = q
            pct = parse_float(row["pct"], "pct", f"{f.filename} row {i}", ctx.issues, 0, 100)
            if pct is None:
                continue
            subgroup = row.get("subgroup") or "all"
            totals[(row["question_wording"], subgroup)] += pct
            party = r.party(row.get("party"), ref) if row.get("party") else None
            ctx.db.add(
                PollResult(
                    question_id=q.id,
                    choice=row["choice"],
                    party_id=party.id if party else None,
                    pct=pct,
                    subgroup=subgroup,
                )
            )
        for (_wording, subgroup), total in totals.items():
            if total > 101.0:
                ctx.quarantine(
                    Issue(ref, "pct_sum", f"responses for {subgroup!r} sum to {total:.1f}% (>101%)", severity="warning")
                )
        ctx.count("polls")


register(EditorialContestsAdapter())
register(OfficialResultsAdapter())
register(PollsAdapter())

__all__ = ["StructuralError"]
