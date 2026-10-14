"""Read APIs: overview, explorer, results monitoring, maps, polls, issues, forecasts, sources."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal, get_db, require
from ..models import (
    AdminUnit,
    Contest,
    Country,
    District,
    DistrictPlan,
    Election,
    ElectionCycle,
    ForecastRun,
    IngestionRun,
    ModelVersion,
    Office,
    QuarantineItem,
    Source,
)
from ..services import issues, polling, results
from ..services.freshness import source_freshness
from .deps import rate_limited

router = APIRouter(prefix="/api/v1", dependencies=[Depends(rate_limited)])
READ = Depends(require("data:read"))


def _404(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


@router.get("/countries")
def countries(db: Session = Depends(get_db), p: Principal = READ) -> list[dict]:
    out = []
    for c in db.scalars(select(Country).order_by(Country.is_synthetic, Country.code)):
        cycles = db.scalars(select(ElectionCycle.key).where(ElectionCycle.country_code == c.code)
                            .order_by(ElectionCycle.year.desc())).all()
        offices = db.execute(select(Office.key, Office.name).where(Office.country_code == c.code)).all()
        out.append({"code": c.code, "name": c.name, "is_synthetic": c.is_synthetic, "cycles": cycles,
                    "offices": [{"key": k, "name": n} for k, n in offices], "timezone": c.default_timezone,
                    "publication_rules": c.publication_rules})
    return out


@router.get("/overview")
def overview(country: str, cycle: str, db: Session = Depends(get_db), p: Principal = READ) -> dict:
    c = db.get(Country, country)
    if c is None:
        raise _404("country")
    elections = db.execute(select(Election.kind, Election.election_date, Election.date_basis, AdminUnit.abbreviation)
                           .join(ElectionCycle).outerjoin(AdminUnit, AdminUnit.id == Election.admin_unit_id)
                           .where(ElectionCycle.country_code == country, ElectionCycle.key == cycle)
                           .order_by(Election.election_date)).all()
    contests = results.list_contests(db, country=country, cycle=cycle, limit=5000)
    by_office = Counter(r["office"] for r in contests)
    by_status = Counter(r["status"] or "no_results" for r in contests)
    srcs = [s for s in db.scalars(select(Source)) if country in (s.coverage or {}).get("countries", []) or
            "*" in (s.coverage or {}).get("countries", [])]
    return {
        "country": {"code": c.code, "name": c.name, "is_synthetic": c.is_synthetic},
        "cycle": cycle,
        "calendar": [{"kind": k, "date": d, "basis": b, "admin_unit": a} for k, d, b, a in elections],
        "contests_by_office": dict(by_office), "results_by_status": dict(by_status), "contest_count": len(contests),
        "sources": [{"key": s.key, "name": s.name, "status": s.status, "status_reason": s.status_reason,
                     "remediation": s.remediation, "freshness": source_freshness(s), "data_kind": s.data_kind,
                     "is_synthetic": s.is_synthetic} for s in srcs],
        "definitions": {
            "margin_pct": "Vote share of the leading line minus the second line, in percentage points.",
            "status": results.STATUS_LABELS,
        },
        "generated_at": datetime.now(UTC),
    }


@router.get("/contests")
def contests(country: str, cycle: str, office: str | None = None, admin_unit: str | None = None,
             limit: int = Query(500, le=5000), db: Session = Depends(get_db), p: Principal = READ) -> dict:
    rows = results.list_contests(db, country=country, cycle=cycle, office=office, admin_unit=admin_unit, limit=limit)
    synthetic = bool(db.scalar(select(Country.is_synthetic).where(Country.code == country)))
    return {"contests": rows, "is_synthetic": synthetic, "count": len(rows),
            "metric_definitions": {"margin_pct": "Leader share minus runner-up share (percentage points).",
                                   "reporting_pct": "Only shown when the publishing source reports completeness."}}


@router.get("/contests/{contest_id}")
def contest(contest_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = READ) -> dict:
    det = results.contest_detail(db, contest_id)
    if det is None:
        raise _404("contest")
    return det


@router.get("/districts/{district_id}/history")
def district_history(district_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = READ) -> dict:
    try:
        return results.district_history(db, district_id)
    except LookupError as exc:
        raise _404("district") from exc


@router.get("/districts/compatibility")
def compatibility(a: uuid.UUID, b: uuid.UUID, db: Session = Depends(get_db), p: Principal = READ) -> dict:
    try:
        return results.compatibility(db, a, b)
    except LookupError as exc:
        raise _404("district") from exc


@router.get("/map")
def district_map(country: str, cycle: str, office: str, db: Session = Depends(get_db), p: Principal = READ) -> dict:
    rows = {r["district_id"]: r for r in results.list_contests(db, country=country, cycle=cycle, office=office,
                                                                limit=5000) if r["district_id"]}
    features = []
    plans = set()
    for d in db.scalars(select(District).where(District.id.in_([uuid.UUID(i) for i in rows]))):
        r = rows[str(d.id)]
        plans.add(d.plan_id)
        if d.geometry is None:
            continue
        features.append({"type": "Feature", "geometry": d.geometry, "properties": {
            "district": d.code, "contest_id": r["id"], "status": r["status"], "leader": r["top"][0]["party"]
            if r["top"] else None, "margin_pct": r["margin_pct"], "name": r["name"]}})
    plan_rows = db.scalars(select(DistrictPlan).where(DistrictPlan.id.in_(plans))).all() if plans else []
    return {"type": "FeatureCollection", "features": features, "plans": [
        {"name": pl.name, "boundary_status": pl.boundary_status, "valid_from": pl.valid_from, "valid_to": pl.valid_to}
        for pl in plan_rows], "districts_without_geometry": len(rows) - len(features)}


@router.get("/results/monitor")
def monitor(country: str, cycle: str, db: Session = Depends(get_db), p: Principal = READ) -> dict:
    rows = results.list_contests(db, country=country, cycle=cycle, limit=5000)
    with_results = [r for r in rows if r["status"]]
    return {"counts": dict(Counter(r["status"] or "awaiting" for r in rows)),
            "reporting_supported": sum(r["reporting_pct"] is not None for r in with_results),
            "recent": sorted(with_results, key=lambda r: r["retrieved_at"], reverse=True)[:50],
            "status_definitions": results.STATUS_LABELS,
            "note": "Race calls are shown only from sources authorized by the editorial policy. The platform does "
                    "not call races automatically."}


# ------------------------------------------------------------------ polling

@router.get("/polls")
def polls(country: str, scope: str | None = None, contest_id: uuid.UUID | None = None,
          db: Session = Depends(get_db), p: Principal = READ) -> dict:
    return {"polls": polling.list_polls(db, country=country, scope=scope, contest_id=contest_id)}


@router.get("/polls/average")
def poll_average(country: str, scope: str = "generic_ballot", as_of: date | None = None,
                 window_days: int = Query(60, ge=7, le=365), db: Session = Depends(get_db), p: Principal = READ) -> dict:
    as_of = as_of or datetime.now(UTC).date()
    avg = polling.average(db, country=country, scope=scope, as_of=as_of, window_days=window_days)
    trend = []
    for k in range(0, window_days, 7):
        d = as_of - timedelta(days=k)
        a = polling.average(db, country=country, scope=scope, as_of=d, window_days=window_days)
        if a["available"]:
            trend.append({"as_of": d, **{c: v["mean"] for c, v in a["estimates"].items()}})
    return {**avg, "trend": list(reversed(trend))}


# ------------------------------------------------------------------ issues

@router.get("/issues/trends")
def issue_trends(country: str, weeks: int = Query(12, ge=1, le=104), db: Session = Depends(get_db),
                 p: Principal = READ) -> dict:
    end = datetime.now(UTC)
    tr = issues.topic_trends(db, country=country, start=end - timedelta(weeks=weeks), end=end)
    tr["scope_note"] = ("Share of de-duplicated covered documents that mention each topic. Not sentiment, not support, "
                        "not voting intention; coverage depends on licensed sources.")
    return tr


@router.get("/issues/evaluation")
def issue_eval(db: Session = Depends(get_db), p: Principal = READ) -> dict:
    ev = issues.evaluate(db)
    return {"model_version": ev.model_version, "n_documents": ev.n_documents, "micro": ev.micro,
            "per_topic": ev.per_topic, "labels_synthetic_only": ev.labeled_by_synthetic_only,
            "caveat": "Evaluated on generator-labelled SYNTHETIC text; not evidence of real-world accuracy."
            if ev.labeled_by_synthetic_only else "Human-labelled evaluation set."}


# ------------------------------------------------------------------ forecasts

def _run_view(r: ForecastRun, full: bool) -> dict:
    v = {"id": str(r.id), "country": r.country_code, "office": r.office_key, "cycle": r.cycle_key, "kind": r.kind,
         "status": r.status, "data_cutoff": r.data_cutoff, "created_at": r.created_at, "published_at": r.published_at,
         "uses_synthetic_data": r.uses_synthetic_data, "gate_results": r.gate_results, "scenario": r.scenario}
    if full:
        v.update({"assumptions": r.assumptions, "inputs_summary": r.inputs_summary, "backtest": r.backtest,
                  "aggregate_outputs": r.aggregate_outputs, "contest_outputs": r.contest_outputs,
                  "random_seed": r.random_seed})
    return v


@router.get("/forecasts")
def forecasts(country: str, db: Session = Depends(get_db), p: Principal = Depends(require("forecasts:read"))) -> dict:
    runs = db.scalars(select(ForecastRun).where(ForecastRun.country_code == country)
                      .order_by(ForecastRun.created_at.desc()).limit(50)).all()
    return {"runs": [_run_view(r, False) for r in runs if r.status == "published" or p.has("forecasts:run")
                     or r.status == "blocked"]}


@router.get("/forecasts/{run_id}")
def forecast(run_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = Depends(require("forecasts:read"))) -> dict:
    r = db.get(ForecastRun, run_id)
    if r is None:
        raise _404("forecast")
    mv = db.get(ModelVersion, r.model_version_id)
    view = _run_view(r, True)
    if r.status != "published" and not p.has("forecasts:run"):
        # Unpublished estimates are not shown to tenants; only the gate outcomes are.
        for k in ("aggregate_outputs", "contest_outputs"):
            view[k] = None
        view["withheld_reason"] = "Forecast outputs are withheld until every publication gate passes."
    view["model_version"] = {"version": mv.version, "description": mv.description, "params": mv.params} if mv else None
    return view


# ------------------------------------------------------------------ sources

@router.get("/sources")
def sources(db: Session = Depends(get_db), p: Principal = READ) -> dict:
    out = []
    for s in db.scalars(select(Source).order_by(Source.is_synthetic, Source.key)):
        last_run = db.scalar(select(IngestionRun).where(IngestionRun.source_id == s.id)
                             .order_by(IngestionRun.started_at.desc()).limit(1))
        open_q = db.scalar(select(func.count()).select_from(QuarantineItem).where(
            QuarantineItem.source_id == s.id, QuarantineItem.status == "open"))
        out.append({c: getattr(s, c) for c in (
            "key", "name", "publisher", "owner_team", "homepage_url", "access_method", "access_details", "access_terms",
            "license", "license_url", "permits_redistribution", "permits_text_analysis", "refresh_schedule",
            "freshness_sla_hours", "coverage", "reliability_notes", "data_kind", "status", "status_reason",
            "remediation", "required_credentials", "is_synthetic", "verification", "last_success_at")}
            | {"freshness": source_freshness(s), "open_quarantine": open_q,
               "last_run": {"id": str(last_run.id), "status": last_run.status, "started_at": last_run.started_at,
                            "stats": last_run.stats, "error": last_run.error} if last_run else None})
    return {"sources": out}


@router.get("/sources/{key}/runs")
def source_runs(key: str, db: Session = Depends(get_db), p: Principal = READ) -> dict:
    s = db.scalar(select(Source).where(Source.key == key))
    if s is None:
        raise _404("source")
    runs = db.scalars(select(IngestionRun).where(IngestionRun.source_id == s.id)
                      .order_by(IngestionRun.started_at.desc()).limit(50)).all()
    return {"runs": [{"id": str(r.id), "status": r.status, "adapter": r.adapter_key, "version": r.adapter_version,
                      "started_at": r.started_at, "finished_at": r.finished_at, "stats": r.stats, "checks": r.checks,
                      "error": r.error, "raw_file_ids": r.raw_file_ids, "triggered_by": r.triggered_by} for r in runs]}
