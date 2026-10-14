"""MIT Election Data and Science Lab constituency returns (U.S. House / Senate CSV)."""

from __future__ import annotations

from collections import defaultdict

from ...countries.us import UnitedStatesAdapter, federal_general_election_date
from ..framework import FetchedFile, Issue, RunContext, SourceAdapter, StructuralError, register
from ..loaders import Resolver, normalize_label
from ..results_writer import Line, write_snapshot
from ..validation import check_totals, parse_bool, parse_int, read_csv

REQUIRED = ("year", "state_po", "office", "district", "stage", "special", "candidate", "party", "writein",
            "candidatevotes", "totalvotes")
OFFICES = {"US HOUSE": "us_house", "US SENATE": "us_senate"}
US = UnitedStatesAdapter()


class MedslReturnsAdapter(SourceAdapter):
    key = "medsl_returns"
    version = "1.0.0"
    schema_version = "medsl-constituency-returns-v1"

    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        stages = set(ctx.params.get("stages", ["GEN"]))
        years = set(ctx.params.get("years", []))
        r = Resolver(ctx, "US")
        for f in files:
            rows = read_csv(f.content, REQUIRED, ref=f.filename or f.url)
            raw = ctx.raw_file_for(f)
            groups: dict[tuple, list[tuple[int, dict]]] = defaultdict(list)
            for i, row in enumerate(rows, start=2):
                ref = f"{f.filename or 'file'} row {i}"
                office_key = OFFICES.get(row["office"].upper())
                if office_key is None:
                    ctx.quarantine(Issue(ref, "office_unknown", f"unknown office {row['office']!r}"))
                    continue
                if row["stage"].upper() not in stages:
                    ctx.count("rows_skipped_stage")
                    continue
                if years and int(row["year"]) not in years:
                    continue
                if parse_bool(row["special"]):
                    ctx.quarantine(Issue(ref, "special_election_date",
                                         "Special-election rows are not loaded: the file has no election date",
                                         severity="warning",
                                         suggested_action="Load specials via the editorial calendar with a cited "
                                                          "date, then re-run."))
                    continue
                groups[(int(row["year"]), row["state_po"].upper(), office_key, row["district"])].append((i, row))
            if not groups and rows:
                ctx.check("rows_loaded", False, "no rows matched the requested stages/years")
            for (year, state, office_key, district), items in groups.items():
                self._load_contest(ctx, r, raw.id, f, year, state, office_key, district, items)
        ctx.check("schema", True, ", ".join(REQUIRED))

    def _load_contest(self, ctx: RunContext, r: Resolver, raw_file_id, f: FetchedFile, year: int,  # type: ignore[no-untyped-def]
                      state: str, office_key: str, district: str, items: list[tuple[int, dict]]) -> None:
        ref = f"{f.filename or 'file'} rows {items[0][0]}-{items[-1][0]} ({year} {state} {office_key} {district})"
        unit = r.unit(state)
        if unit is None:
            ctx.quarantine(Issue(ref, "geo_join", f"state {state!r} not in reference geography"))
            return
        try:
            edate = federal_general_election_date(year)
        except ValueError:
            ctx.quarantine(Issue(ref, "election_date", f"{year} is not a federal general election year"))
            return
        election = r.election(year, "general", edate, unit.timezone or "America/New_York",
                              "2 U.S.C. 7 (date derived by rule; MEDSL rows carry no date)")
        office = r.office(office_key)
        issues: list[Issue] = []
        if office_key == "us_house":
            n = parse_int(district, "district", ref, issues)
            if n is None:
                ctx.issues.extend(issues)
                return
            code = f"{state}-AL" if n == 0 else f"{state}-{n:02d}"
            plan = r.plan_as_contested(office, unit, year)
            dist = r.district(plan, code, f"{unit.name} {'at-large' if n == 0 else f'district {n}'}", unit)
            contest = r.contest(election, office, f"U.S. House {code} ({year})",
                                US.system_for("us_house", unit.code, "general"), district=dist, unit=unit)
        else:
            contest = r.contest(election, office, f"U.S. Senate {state} ({year})",
                                US.system_for("us_senate", unit.code, "general"), unit=unit)

        # Fusion tickets list one candidate on several party lines: aggregate by candidate.
        by_cand: dict[str, dict] = {}
        totals: set[int] = set()
        seen_lines: set[tuple] = set()
        for i, row in items:
            rref = f"{f.filename or 'file'} row {i}"
            votes = parse_int(row["candidatevotes"], "candidatevotes", rref, issues)
            total = parse_int(row["totalvotes"], "totalvotes", rref, issues)
            if votes is None:
                continue
            if total is not None:
                totals.add(total)
            dup_key = (normalize_label(row["candidate"]), normalize_label(row["party"]), votes)
            if dup_key in seen_lines:
                issues.append(Issue(rref, "duplicate", f"duplicate row for {row['candidate']!r}", severity="warning",
                                    suggested_action="Duplicate dropped; confirm with publisher."))
                continue
            seen_lines.add(dup_key)
            name = row["candidate"] or "UNKNOWN"
            entry = by_cand.setdefault(normalize_label(name), {"name": name, "votes": 0, "parties": [],
                                                                "writein": parse_bool(row["writein"])})
            entry["votes"] += votes
            if row["party"]:
                entry["parties"].append((votes, row["party"]))
        ctx.issues.extend(issues)
        if len(totals) > 1:
            ctx.quarantine(Issue(ref, "totals_inconsistent", f"rows disagree on totalvotes: {sorted(totals)}"))
            return
        total = totals.pop() if totals else None
        lines = []
        for e in by_cand.values():
            party_label = max(e["parties"])[1] if e["parties"] else None
            party = r.party(party_label, ref) if party_label else None
            if e["writein"] or normalize_label(e["name"]) in ("WRITEIN", "SCATTERING", "OTHER", "BLANK", "OVER VOTES",
                                                               "UNDER VOTES"):
                lines.append(Line(e["name"], e["votes"], party_label, None, is_writein=True))
                continue
            cand = r.candidate(e["name"], unit)
            cy = r.candidacy(contest, cand, e["name"], party, status="on_ballot")
            lines.append(Line(e["name"], e["votes"], party_label, cy))
        problem = check_totals(sum(ln.votes for ln in lines if ln.label.upper() not in ("BLANK", "OVER VOTES",
                                                                                          "UNDER VOTES")),
                               total, ref, tolerance=0.02)
        if problem is not None:
            ctx.quarantine(problem)
            if problem.severity == "error":
                return
        unofficial = any(parse_bool(row.get("unofficial", "")) for _, row in items)
        write_snapshot(ctx, contest, status="unofficial" if unofficial else "certified", lines=lines,
                       retrieved_at=f.retrieved_at, raw_file_id=raw_file_id, record_ref=ref, total_votes=total)
        ctx.count("contests_loaded")


register(MedslReturnsAdapter())

__all__ = ["MedslReturnsAdapter", "StructuralError"]
