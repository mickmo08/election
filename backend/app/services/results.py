"""Results, contest views, seat allocation and boundary-aware historical comparison."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..models import (
    AdminUnit,
    Candidacy,
    Contest,
    District,
    DistrictCrosswalk,
    DistrictPlan,
    Election,
    ElectionCycle,
    Office,
    Party,
    RaceCall,
    ResultSnapshot,
    Source,
)

STATUS_LABELS = {
    "preliminary": "Preliminary — counting in progress; totals will change",
    "unofficial": "Unofficial — count complete or nearly complete, not yet certified",
    "certified": "Certified by the responsible authority",
    "corrected": "Corrected — supersedes an earlier published result",
    "recount": "Recount — totals from an official recount",
}


def dhondt(votes: dict[str, int], seats: int) -> dict[str, int]:
    alloc = dict.fromkeys(votes, 0)
    for _ in range(seats):
        best = max(votes, key=lambda p: (votes[p] / (alloc[p] + 1), votes[p]))
        alloc[best] += 1
    return alloc


def winners(system: str, seats: int, lines: list[dict]) -> dict:
    """Outcome *implied by the reported count* under the contest's system. Not a race call."""
    counted = [ln for ln in lines if not ln["is_writein"]] or lines
    total = sum(ln["votes"] for ln in lines) or 1
    if system == "list_pr_dhondt":
        alloc = dhondt({ln["label"]: ln["votes"] for ln in counted}, seats)
        return {"kind": "seat_allocation", "method": "D'Hondt", "seats": alloc}
    ranked = sorted(counted, key=lambda ln: ln["votes"], reverse=True)
    if not ranked:
        return {"kind": "none"}
    lead = ranked[0]
    if system == "two_round_majority" and lead["votes"] / total <= 0.5:
        return {
            "kind": "runoff_required",
            "advancing": [r["label"] for r in ranked[:2]],
            "note": "No candidate exceeds 50% of votes counted.",
        }
    if system == "rcv_irv" and lead["votes"] / total <= 0.5:
        return {
            "kind": "rcv_tabulation_required",
            "note": "First-choice leader is below 50%; the outcome depends on ranked tabulation by the authority.",
        }
    if system in ("top_two_primary", "top_four_primary"):
        k = 2 if system == "top_two_primary" else 4
        return {"kind": "advancing", "advancing": [r["label"] for r in ranked[:k]]}
    return {
        "kind": "plurality_leader",
        "leader": lead["label"],
        "margin_votes": lead["votes"] - (ranked[1]["votes"] if len(ranked) > 1 else 0),
    }


def snapshot_view(s: ResultSnapshot, parties: dict, sources: dict) -> dict:
    total = sum(ln.votes for ln in s.lines) or 0
    src = sources.get(s.source_id)
    return {
        "id": str(s.id),
        "status": s.status,
        "status_label": STATUS_LABELS[s.status],
        "source": {"key": src.key, "name": src.name, "publisher": src.publisher, "is_synthetic": src.is_synthetic}
        if src
        else None,
        "source_as_of": s.source_as_of,
        "retrieved_at": s.retrieved_at,
        "reporting_pct": s.reporting_pct if s.reporting_supported else None,
        "reporting_supported": s.reporting_supported,
        "total_votes": s.total_votes,
        "turnout": (
            {
                "pct": round(100 * s.total_votes / s.eligible_or_registered, 2),
                "denominator": s.turnout_denominator_kind,
                "eligible": s.eligible_or_registered,
            }
            if s.eligible_or_registered and s.total_votes
            else None
        ),
        "supersedes_id": str(s.supersedes_id) if s.supersedes_id else None,
        "correction_note": s.correction_note,
        "disputed": s.disputed,
        "dispute_note": s.dispute_note,
        "lines": [
            {
                "label": ln.label,
                "party": ln.party_label,
                "votes": ln.votes,
                "is_writein": ln.is_writein,
                "share": round(100 * ln.votes / total, 2) if total else None,
                "candidacy_id": str(ln.candidacy_id) if ln.candidacy_id else None,
            }
            for ln in s.lines
        ],
    }


def contest_detail(db: Session, contest_id: uuid.UUID) -> dict | None:
    c = db.scalar(
        select(Contest)
        .where(Contest.id == contest_id)
        .options(selectinload(Contest.election), selectinload(Contest.office), selectinload(Contest.district))
    )
    if c is None:
        return None
    snaps = list(
        db.scalars(
            select(ResultSnapshot)
            .where(ResultSnapshot.contest_id == c.id)
            .options(selectinload(ResultSnapshot.lines))
            .order_by(ResultSnapshot.retrieved_at)
        )
    )
    sources = {s.id: s for s in db.scalars(select(Source))}
    parties = {p.id: p for p in db.scalars(select(Party))}
    cands = list(
        db.scalars(
            select(Candidacy)
            .where(Candidacy.contest_id == c.id)
            .options(selectinload(Candidacy.candidate), selectinload(Candidacy.party))
        )
    )
    current = snaps[-1] if snaps else None
    view_current = snapshot_view(current, parties, sources) if current else None
    calls = _race_calls(db, c.id, sources)
    cycle = db.get(ElectionCycle, c.election.cycle_id)
    unit = db.get(AdminUnit, c.admin_unit_id) if c.admin_unit_id else None
    plan = db.get(DistrictPlan, c.district.plan_id) if c.district else None
    src = sources.get(c.source_id)
    synthetic = bool(src and src.is_synthetic) or any(sources[s.source_id].is_synthetic for s in snaps)
    return {
        "id": str(c.id),
        "name": c.name,
        "office": {"key": c.office.key, "name": c.office.name},
        "electoral_system": c.electoral_system,
        "seats": c.seats,
        "is_special": c.is_special,
        "seat_class": c.seat_class,
        "country": cycle.country_code if cycle else None,
        "election": {
            "kind": c.election.kind,
            "date": c.election.election_date,
            "date_basis": c.election.date_basis,
            "cycle": cycle.key if cycle else None,
            "timezone": c.election.timezone,
        },
        "admin_unit": {"code": unit.code, "name": unit.name, "abbreviation": unit.abbreviation} if unit else None,
        "district": {
            "id": str(c.district.id),
            "code": c.district.code,
            "name": c.district.name,
            "plan": plan.name if plan else None,
            "boundary_status": plan.boundary_status if plan else None,
            "has_geometry": c.district.geometry is not None,
        }
        if c.district
        else None,
        "candidates": [
            {
                "id": str(cy.id),
                "name": cy.ballot_name,
                "party": cy.party.name if cy.party else None,
                "party_abbr": cy.party.abbreviation if cy.party else None,
                "party_color": cy.party.color if cy.party else None,
                "incumbent": cy.incumbent,
                "status": cy.status,
            }
            for cy in cands
        ],
        "current": view_current,
        "implied_outcome": winners(c.electoral_system, c.seats, view_current["lines"]) if view_current else None,
        "race_calls": calls,
        "history": [
            {
                "id": str(s.id),
                "status": s.status,
                "retrieved_at": s.retrieved_at,
                "source_as_of": s.source_as_of,
                "reporting_pct": s.reporting_pct if s.reporting_supported else None,
                "total_votes": s.total_votes,
                "supersedes_id": str(s.supersedes_id) if s.supersedes_id else None,
                "correction_note": s.correction_note,
            }
            for s in snaps
        ],
        "provenance": {
            "contest_source": src.key if src else None,
            "ingestion_run_id": str(c.ingestion_run_id) if c.ingestion_run_id else None,
        },
        "is_synthetic": synthetic,
    }


def _race_calls(db: Session, contest_id: uuid.UUID, sources: dict) -> list[dict]:
    authorized = set(get_settings().authorized_race_call_sources)
    out = []
    for rc in db.scalars(select(RaceCall).where(RaceCall.contest_id == contest_id).order_by(RaceCall.called_at)):
        src = sources[rc.caller_source_id]
        if src.key not in authorized:
            continue  # never display calls from sources outside the editorial policy
        cy = db.get(Candidacy, rc.candidacy_id)
        out.append(
            {
                "id": str(rc.id),
                "candidacy_id": str(rc.candidacy_id),
                "candidate": cy.ballot_name if cy else None,
                "called_at": rc.called_at,
                "status": rc.status,
                "caller": src.name,
                "note": rc.note,
            }
        )
    return out


def record_race_call(
    db: Session,
    *,
    contest_id: uuid.UUID,
    candidacy_id: uuid.UUID,
    caller_source_key: str,
    recorded_by: str,
    note: str = "",
    retract: bool = False,
) -> RaceCall:
    if caller_source_key not in get_settings().authorized_race_call_sources:
        raise PermissionError(f"{caller_source_key} is not an authorized race-call source under the editorial policy")
    src = db.scalar(select(Source).where(Source.key == caller_source_key))
    cy = db.get(Candidacy, candidacy_id)
    if src is None or cy is None or cy.contest_id != contest_id:
        raise LookupError("unknown source or candidacy for this contest")
    rc = RaceCall(
        contest_id=contest_id,
        candidacy_id=candidacy_id,
        caller_source_id=src.id,
        called_at=datetime.now(UTC),
        status="retracted" if retract else "called",
        note=note,
        recorded_by=recorded_by,
    )
    db.add(rc)
    db.flush()
    return rc


def list_contests(
    db: Session, *, country: str, cycle: str, office: str | None = None, admin_unit: str | None = None, limit: int = 500
) -> list[dict]:
    q = (
        select(Contest, Election, Office, AdminUnit, District)
        .join(Election, Election.id == Contest.election_id)
        .join(ElectionCycle, ElectionCycle.id == Election.cycle_id)
        .join(Office, Office.id == Contest.office_id)
        .outerjoin(AdminUnit, AdminUnit.id == Contest.admin_unit_id)
        .outerjoin(District, District.id == Contest.district_id)
        .where(ElectionCycle.country_code == country, ElectionCycle.key == cycle)
    )
    if office:
        q = q.where(Office.key == office)
    if admin_unit:
        q = q.where((AdminUnit.code == admin_unit) | (AdminUnit.abbreviation == admin_unit))
    rows = db.execute(q.order_by(Office.key, AdminUnit.code, District.code).limit(limit)).all()
    ids = [r[0].id for r in rows]
    latest: dict = {}
    if ids:
        for s in db.scalars(
            select(ResultSnapshot)
            .where(ResultSnapshot.contest_id.in_(ids))
            .options(selectinload(ResultSnapshot.lines))
            .order_by(ResultSnapshot.contest_id, ResultSnapshot.retrieved_at)
        ):
            latest[s.contest_id] = s
    out = []
    for c, e, o, u, d in rows:
        s = latest.get(c.id)
        lines = sorted(s.lines, key=lambda ln: ln.votes, reverse=True) if s else []
        total = sum(ln.votes for ln in lines)
        top = [
            {
                "label": ln.label,
                "party": ln.party_label,
                "votes": ln.votes,
                "share": round(100 * ln.votes / total, 2) if total else None,
            }
            for ln in lines[:3]
        ]
        out.append(
            {
                "id": str(c.id),
                "name": c.name,
                "office": o.key,
                "kind": e.kind,
                "date": e.election_date,
                "admin_unit": u.abbreviation or u.code if u else None,
                "district": d.code if d else None,
                "district_id": str(d.id) if d else None,
                "seats": c.seats,
                "electoral_system": c.electoral_system,
                "status": s.status if s else None,
                "reporting_pct": s.reporting_pct if s and s.reporting_supported else None,
                "total_votes": s.total_votes if s else None,
                "top": top,
                "margin_pct": round(top[0]["share"] - top[1]["share"], 2) if len(top) > 1 and total else None,
                "retrieved_at": s.retrieved_at if s else None,
            }
        )
    return out


def compatibility(db: Session, district_a: uuid.UUID, district_b: uuid.UUID) -> dict:
    """Can results in district A be compared with district B as 'the same place'?"""
    a, b = db.get(District, district_a), db.get(District, district_b)
    if a is None or b is None:
        raise LookupError("district not found")
    pa, pb = db.get(DistrictPlan, a.plan_id), db.get(DistrictPlan, b.plan_id)
    if a.plan_id == b.plan_id and a.id == b.id:
        return {"comparable": True, "basis": "same_district", "detail": "Same district in the same plan."}

    def root(p: DistrictPlan) -> uuid.UUID:
        seen = set()
        while p.same_boundaries_as_id and p.id not in seen:
            seen.add(p.id)
            p = db.get(DistrictPlan, p.same_boundaries_as_id)
        return p.id

    if root(pa) == root(pb) and a.code == b.code:
        return {
            "comparable": True,
            "basis": "identical_boundaries",
            "detail": f"'{pa.name}' and '{pb.name}' are recorded as having identical boundaries.",
        }
    cw = db.scalar(
        select(DistrictCrosswalk).where(
            ((DistrictCrosswalk.from_district_id == a.id) & (DistrictCrosswalk.to_district_id == b.id))
            | ((DistrictCrosswalk.from_district_id == b.id) & (DistrictCrosswalk.to_district_id == a.id))
        )
    )
    if cw is not None:
        return {
            "comparable": cw.population_share >= 0.6,
            "basis": "crosswalk",
            "overlap_share": cw.population_share,
            "method": cw.method,
            "detail": f"Boundaries changed; {cw.population_share:.0%} population overlap ({cw.method}). "
            + (
                "Comparison shown with caution."
                if cw.population_share >= 0.6
                else "Overlap too small for a like-for-like comparison."
            ),
        }
    reason = (
        "boundaries for at least one plan are not loaded"
        if "identifiers_only" in (pa.boundary_status, pb.boundary_status)
        else "no crosswalk between the plans"
    )
    return {
        "comparable": False,
        "basis": "unknown",
        "detail": f"Not comparable: '{pa.name}' vs '{pb.name}' — {reason}. A matching district code does not "
        "imply matching boundaries.",
    }


def district_history(db: Session, district_id: uuid.UUID) -> dict:
    """Results for a district across cycles, each annotated with boundary compatibility."""
    d = db.get(District, district_id)
    if d is None:
        raise LookupError("district not found")
    plan = db.get(DistrictPlan, d.plan_id)
    same_code = db.scalars(
        select(District)
        .join(DistrictPlan)
        .where(
            District.code == d.code,
            DistrictPlan.office_id == plan.office_id,
            DistrictPlan.admin_unit_id == plan.admin_unit_id,
        )
    ).all()
    rows = []
    for other in same_code:
        for c in db.scalars(select(Contest).where(Contest.district_id == other.id)):
            det = contest_detail(db, c.id)
            if not det or not det["current"]:
                continue
            lines = det["current"]["lines"]
            rows.append(
                {
                    "contest_id": det["id"],
                    "cycle": det["election"]["cycle"],
                    "kind": det["election"]["kind"],
                    "status": det["current"]["status"],
                    "lines": lines[:3],
                    "compatibility": compatibility(db, district_id, other.id),
                }
            )
    rows.sort(key=lambda r: r["cycle"] or "")
    return {"district": {"id": str(d.id), "code": d.code, "plan": plan.name}, "history": rows}
