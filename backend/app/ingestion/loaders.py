"""Shared load helpers: identity resolution for parties/candidates and structure get-or-create.

Identity resolution policy (docs/data/identity-resolution.md):
  * Parties resolve by canonical key or alias (case/punctuation-insensitive). Unknown labels
    create a provisional party and a warning for steward review.
  * Candidates resolve by publisher ID (e.g. FEC candidate ID) when present. Without an ID,
    candidates resolve only within (country, admin unit, normalized name) and the match is
    recorded as name-based so analysts can see its lower confidence.
"""

from __future__ import annotations

import re
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AdminUnit,
    Candidacy,
    Candidate,
    Contest,
    District,
    DistrictPlan,
    Election,
    ElectionCycle,
    Office,
    Party,
)
from .framework import Issue, RunContext

_norm_re = re.compile(r"[^A-Z0-9 ]+")


def normalize_label(s: str) -> str:
    return " ".join(_norm_re.sub(" ", s.upper().replace("&", " AND ")).split())


class Resolver:
    """Per-run caches so large files don't issue one query per row."""

    def __init__(self, ctx: RunContext, country_code: str) -> None:
        self.ctx = ctx
        self.db = ctx.db
        self.country = country_code
        self._parties: dict[str, Party] = {}
        for p in self.db.scalars(select(Party).where(Party.country_code == country_code)):
            self._index_party(p)
        self._units = {u.abbreviation or u.code: u for u in self.db.scalars(
            select(AdminUnit).where(AdminUnit.country_code == country_code))}
        self._units_by_code = {u.code: u for u in self._units.values()}
        self._offices = {o.key: o for o in self.db.scalars(select(Office).where(Office.country_code == country_code))}
        self._cache: dict[tuple, object] = {}

    def _index_party(self, p: Party) -> None:
        for label in [p.key, p.name, p.abbreviation or "", *(p.aliases or [])]:
            if label:
                self._parties[normalize_label(label)] = p

    # ------------------------------------------------------------------ reference lookups
    def unit(self, abbr_or_code: str) -> AdminUnit | None:
        return self._units.get(abbr_or_code) or self._units_by_code.get(abbr_or_code)

    def office(self, key: str) -> Office:
        return self._offices[key]

    def party(self, label: str | None, record_ref: str) -> Party | None:
        if not label or not label.strip():
            return None
        n = normalize_label(label)
        if n in self._parties:
            return self._parties[n]
        key = "prov_" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:50]
        p = self.db.scalar(select(Party).where(Party.country_code == self.country, Party.key == key))
        if p is None:
            p = Party(country_code=self.country, key=key, name=label.strip().title(), aliases=[label])
            self.db.add(p)
            self.db.flush()
            self.ctx.quarantine(Issue(record_ref, "party_unresolved",
                                      f"Party label {label!r} matched no canonical party; provisional party created",
                                      severity="warning",
                                      suggested_action="Map the label to a canonical party alias or confirm it "
                                                       "is a distinct party."))
            self.ctx.count("provisional_parties")
        self._index_party(p)
        return p

    # ------------------------------------------------------------------ structure
    def cycle(self, year: int) -> ElectionCycle:
        k = ("cycle", year)
        if k not in self._cache:
            c = self.db.scalar(select(ElectionCycle).where(ElectionCycle.country_code == self.country,
                                                           ElectionCycle.key == str(year)))
            if c is None:
                c = ElectionCycle(country_code=self.country, key=str(year), name=f"{self.country} {year}", year=year)
                self.db.add(c)
                self.db.flush()
            self._cache[k] = c
        return self._cache[k]  # type: ignore[return-value]

    def election(self, year: int, kind: str, election_date: date, timezone: str, basis: str,
                 unit: AdminUnit | None = None) -> Election:
        k = ("election", year, kind, election_date, unit.id if unit else None)
        if k not in self._cache:
            cycle = self.cycle(year)
            q = select(Election).where(Election.cycle_id == cycle.id, Election.kind == kind,
                                       Election.election_date == election_date)
            q = q.where(Election.admin_unit_id == unit.id) if unit else q.where(Election.admin_unit_id.is_(None))
            e = self.db.scalar(q)
            if e is None:
                e = Election(cycle_id=cycle.id, kind=kind, election_date=election_date, timezone=timezone,
                             date_basis=basis, admin_unit_id=unit.id if unit else None,
                             source_id=self.ctx.source.id)
                self.db.add(e)
                self.db.flush()
            self._cache[k] = e
        return self._cache[k]  # type: ignore[return-value]

    def plan_as_contested(self, office: Office, unit: AdminUnit, year: int) -> DistrictPlan:
        """Identifier-only plan for districts as contested in `year` (boundaries unknown)."""
        name = f"{office.name} districts in {unit.name} as contested in {year}"
        k = ("plan", office.id, unit.id, name)
        if k not in self._cache:
            p = self.db.scalar(select(DistrictPlan).where(DistrictPlan.office_id == office.id,
                                                          DistrictPlan.admin_unit_id == unit.id,
                                                          DistrictPlan.name == name))
            if p is None:
                p = DistrictPlan(office_id=office.id, admin_unit_id=unit.id, name=name, valid_from=date(year, 1, 1),
                                 valid_to=date(year, 12, 31), source_id=self.ctx.source.id,
                                 boundary_status="identifiers_only",
                                 notes="Created from results/candidate data; boundaries not loaded. Comparisons "
                                       "with other plans are disabled until boundaries or a crosswalk are loaded.")
                self.db.add(p)
                self.db.flush()
            self._cache[k] = p
        return self._cache[k]  # type: ignore[return-value]

    def district(self, plan: DistrictPlan, code: str, name: str, unit: AdminUnit, magnitude: int = 1) -> District:
        k = ("district", plan.id, code)
        if k not in self._cache:
            d = self.db.scalar(select(District).where(District.plan_id == plan.id, District.code == code))
            if d is None:
                d = District(plan_id=plan.id, code=code, name=name, magnitude=magnitude, admin_unit_id=unit.id)
                self.db.add(d)
                self.db.flush()
            self._cache[k] = d
        return self._cache[k]  # type: ignore[return-value]

    def contest(self, election: Election, office: Office, name: str, electoral_system: str, *,
                district: District | None = None, unit: AdminUnit | None = None, party: Party | None = None,
                seats: int = 1, is_special: bool = False, seat_class: str | None = None) -> Contest:
        k = ("contest", election.id, office.id, district.id if district else None, unit.id if unit else None,
             party.id if party else None, seat_class)
        if k not in self._cache:
            q = select(Contest).where(Contest.election_id == election.id, Contest.office_id == office.id)
            for col, val in ((Contest.district_id, district.id if district else None),
                             (Contest.admin_unit_id, unit.id if unit else None),
                             (Contest.party_id, party.id if party else None), (Contest.seat_class, seat_class)):
                q = q.where(col.is_(None)) if val is None else q.where(col == val)
            c = self.db.scalar(q)
            if c is None:
                c = Contest(election_id=election.id, office_id=office.id, district_id=district.id if district else None,
                            admin_unit_id=unit.id if unit else None, party_id=party.id if party else None,
                            seat_class=seat_class, name=name, seats=seats, electoral_system=electoral_system,
                            is_special=is_special, source_id=self.ctx.source.id, ingestion_run_id=self.ctx.run.id)
                self.db.add(c)
                self.db.flush()
                self.ctx.count("contests_created")
            self._cache[k] = c
        return self._cache[k]  # type: ignore[return-value]

    def candidate(self, full_name: str, unit: AdminUnit | None, external: dict | None = None) -> Candidate:
        external = {k: v for k, v in (external or {}).items() if v}
        if external:
            idk, idv = next(iter(sorted(external.items())))
            k = ("cand_ext", idk, idv)
            if k not in self._cache:
                c = self.db.scalar(select(Candidate).where(Candidate.country_code == self.country,
                                                           Candidate.external_ids[idk].astext == idv))
                if c is None:
                    c = Candidate(country_code=self.country, full_name=full_name, external_ids=external)
                    self.db.add(c)
                    self.db.flush()
                self._cache[k] = c
            return self._cache[k]  # type: ignore[return-value]
        name_key = f"{self.country}:{unit.code if unit else '-'}:{normalize_label(full_name)}"
        k = ("cand_name", name_key)
        if k not in self._cache:
            c = self.db.scalar(select(Candidate).where(Candidate.country_code == self.country,
                                                       Candidate.external_ids["name_key"].astext == name_key))
            if c is None:
                c = Candidate(country_code=self.country, full_name=full_name,
                              external_ids={"name_key": name_key, "match_basis": "name_within_admin_unit"})
                self.db.add(c)
                self.db.flush()
            self._cache[k] = c
        return self._cache[k]  # type: ignore[return-value]

    def candidacy(self, contest: Contest, candidate: Candidate, ballot_name: str, party: Party | None,
                  incumbent: bool | None = None, status: str = "filed") -> Candidacy:
        k = ("candidacy", contest.id, candidate.id)
        if k not in self._cache:
            cy = self.db.scalar(select(Candidacy).where(Candidacy.contest_id == contest.id,
                                                        Candidacy.candidate_id == candidate.id))
            if cy is None:
                cy = Candidacy(contest_id=contest.id, candidate_id=candidate.id, ballot_name=ballot_name,
                               party_id=party.id if party else None, incumbent=incumbent, status=status,
                               source_id=self.ctx.source.id, ingestion_run_id=self.ctx.run.id)
                self.db.add(cy)
                self.db.flush()
                self.ctx.count("candidacies_created")
            self._cache[k] = cy
        return self._cache[k]  # type: ignore[return-value]


def new_id() -> uuid.UUID:
    return uuid.uuid4()
