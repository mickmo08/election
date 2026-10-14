"""Leakage-safe extraction of forecasting inputs.

Every query takes an explicit `cutoff`. Only information knowable at the cutoff is used:
  * results of elections held strictly before the cutoff;
  * polls whose fieldwork ended at least one day before the cutoff;
  * candidacies (ballot composition) of the target cycle.
Known limitation: historical results are the final values in the database, which may include
corrections published after the cutoff (documented in docs/methodology/forecasting.md).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models import (
    Candidacy,
    Contest,
    District,
    DistrictCrosswalk,
    DistrictPlan,
    Election,
    ElectionCycle,
    Office,
    Party,
    Poll,
    PollQuestion,
    ResultSnapshot,
    Source,
)
from ..polling import select_non_overlapping

FINAL_STATUSES = ("certified", "corrected", "recount")
# Two-party framing per country (documented assumption; multi-party systems need a different model).
MAJOR_PARTIES = {"US": ("dem", "rep"), "XS": ("xs_blue", "xs_orange")}


@dataclass
class ContestRow:
    contest_id: uuid.UUID
    year: int
    election_date: date
    district_id: uuid.UUID
    district_code: str
    unit_code: str | None
    incumbency: int  # +1 party A incumbent, -1 party B incumbent, 0 open/other
    has_a: bool
    has_b: bool
    prev_margin: float | None = None
    prev_basis: str = "none"  # identical_boundaries | crosswalk | none
    prev_overlap: float = 1.0
    margin: float | None = None  # actual two-party margin (A-B)/(A+B); None if not yet held
    synthetic: bool = False


@dataclass
class CycleInputs:
    year: int
    cutoff: date
    election_date: date
    rows: list[ContestRow]
    env_poll: float | None
    n_polls: int
    env_prev_actual: float | None
    used: dict = field(default_factory=dict)  # audit of what was read (for leakage tests)


def _final_margin(
    db: Session, contest_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID, cutoff: date
) -> tuple[float | None, int, int]:
    snap = db.scalar(
        select(ResultSnapshot)
        .where(ResultSnapshot.contest_id == contest_id, ResultSnapshot.status.in_(FINAL_STATUSES))
        .options(selectinload(ResultSnapshot.lines))
        .order_by(ResultSnapshot.retrieved_at.desc())
        .limit(1)
    )
    if snap is None:
        return None, 0, 0
    party_of = {cy.id: cy.party_id for cy in db.scalars(select(Candidacy).where(Candidacy.contest_id == contest_id))}
    va = sum(ln.votes for ln in snap.lines if party_of.get(ln.candidacy_id) == a)
    vb = sum(ln.votes for ln in snap.lines if party_of.get(ln.candidacy_id) == b)
    if va + vb == 0:
        return None, 0, 0
    return (va - vb) / (va + vb), va, vb


def _prior_district(db: Session, d: District) -> list[tuple[District, str, float]]:
    """Districts in earlier plans comparable to `d`, with basis and overlap."""
    plan = db.get(DistrictPlan, d.plan_id)
    out = []
    # identical boundaries: walk same_boundaries_as chain and also plans pointing to this one
    chain = set()
    p = plan
    while p and p.same_boundaries_as_id and p.id not in chain:
        chain.add(p.id)
        p = db.get(DistrictPlan, p.same_boundaries_as_id)
        if p:
            chain.add(p.id)
    chain |= {x.id for x in db.scalars(select(DistrictPlan).where(DistrictPlan.same_boundaries_as_id == plan.id))}
    chain.add(plan.id)
    for other in db.scalars(select(District).where(District.plan_id.in_(chain), District.code == d.code)):
        out.append((other, "identical_boundaries", 1.0))
    for cw in db.scalars(select(DistrictCrosswalk).where(DistrictCrosswalk.to_district_id == d.id)):
        out.append((db.get(District, cw.from_district_id), "crosswalk", cw.population_share))
    return out


def env_from_polls(
    db: Session, country: str, a: Party, b: Party, cutoff: date, window: int = 60, half_life: float = 14.0
) -> tuple[float | None, int, list[str]]:
    last_field_end = cutoff - timedelta(days=1)
    polls = list(
        db.scalars(
            select(Poll)
            .where(
                Poll.country_code == country,
                Poll.question_scope == "generic_ballot",
                Poll.tenant_id.is_(None),
                Poll.field_end <= last_field_end,
                Poll.field_end > cutoff - timedelta(days=window),
            )
            .options(selectinload(Poll.questions).selectinload(PollQuestion.results))
        )
    )
    kept, _ = select_non_overlapping(polls)
    num = wsum = 0.0
    used = []
    for p in kept:
        res = [r for q in p.questions for r in q.results if r.subgroup == "all"]
        pa = sum(r.pct for r in res if r.party_id == a.id)
        pb = sum(r.pct for r in res if r.party_id == b.id)
        if pa + pb == 0:
            continue
        w = 0.5 ** ((cutoff - p.field_end).days / half_life) * min(p.sample_size or 400, 3000) ** 0.5
        num += w * (pa - pb) / (pa + pb)
        wsum += w
        used.append(f"poll:{p.id}:{p.field_end.isoformat()}")
    return (num / wsum if wsum else None), len(used), used


def cycle_inputs(
    db: Session, *, country: str, office_key: str, year: int, cutoff: date, outcome_cutoff: date | None = None
) -> CycleInputs:
    """Inputs as knowable at `cutoff`; outcomes revealed only for elections before `outcome_cutoff`
    (used when assembling *training* rows for a later target cycle)."""
    a_key, b_key = MAJOR_PARTIES[country]
    a = db.scalar(select(Party).where(Party.country_code == country, Party.key == a_key))
    b = db.scalar(select(Party).where(Party.country_code == country, Party.key == b_key))
    office = db.scalar(select(Office).where(Office.country_code == country, Office.key == office_key))
    synthetic_sources = {s.id for s in db.scalars(select(Source).where(Source.is_synthetic.is_(True)))}
    used: dict[str, list] = defaultdict(list)
    contests = db.execute(
        select(Contest, Election)
        .join(Election)
        .join(ElectionCycle)
        .where(
            ElectionCycle.country_code == country,
            ElectionCycle.key == str(year),
            Contest.office_id == office.id,
            Election.kind == "general",
            Contest.district_id.is_not(None),
            Contest.seats == 1,
        )
    ).all()
    rows: list[ContestRow] = []
    edate = None
    prev_year_votes = [0, 0]
    for c, e in contests:
        edate = e.election_date
        cands = list(db.scalars(select(Candidacy).where(Candidacy.contest_id == c.id)))
        inc = 0
        for cy in cands:
            if cy.incumbent and cy.party_id == a.id:
                inc = 1
            elif cy.incumbent and cy.party_id == b.id:
                inc = -1
        d = db.get(District, c.district_id)
        row = ContestRow(
            c.id,
            year,
            e.election_date,
            d.id,
            d.code,
            None,
            inc,
            any(cy.party_id == a.id for cy in cands),
            any(cy.party_id == b.id for cy in cands),
            synthetic=c.source_id in synthetic_sources,
        )
        # Prior result: most recent general election strictly before the cutoff in a comparable district.
        best = None
        for pd, basis, overlap in _prior_district(db, d):
            for pc, pe in db.execute(
                select(Contest, Election)
                .join(Election)
                .where(
                    Contest.district_id == pd.id,
                    Election.kind == "general",
                    Election.election_date < cutoff,
                    Election.election_date < e.election_date,
                )
            ).all():
                if best is None or pe.election_date > best[1].election_date:
                    best = (pc, pe, basis, overlap)
        if best is not None:
            m, va, vb = _final_margin(db, best[0].id, a.id, b.id, cutoff)
            if m is not None:
                row.prev_margin, row.prev_basis, row.prev_overlap = m, best[2], best[3]
                used["prior_results"].append(f"{best[0].id}:{best[1].election_date.isoformat()}")
                prev_year_votes[0] += va
                prev_year_votes[1] += vb
        # Actual outcome only when the election precedes the outcome cutoff (never for the target).
        if e.election_date < (outcome_cutoff or cutoff):
            row.margin = _final_margin(db, c.id, a.id, b.id, cutoff)[0]
            used["outcomes"].append(f"{c.id}:{e.election_date.isoformat()}")
        rows.append(row)
    env, n_polls, poll_ids = env_from_polls(db, country, a, b, cutoff)
    used["polls"] = poll_ids
    env_prev = ((prev_year_votes[0] - prev_year_votes[1]) / sum(prev_year_votes)) if sum(prev_year_votes) else None
    return CycleInputs(year, cutoff, edate or cutoff, rows, env, n_polls, env_prev, dict(used))
