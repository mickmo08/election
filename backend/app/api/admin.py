"""Administration: platform operations (operators) and organization administration (tenant admins)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, entitlements, queue
from ..auth import Principal, get_db, require
from ..models import (
    AuditEvent,
    Contest,
    ForecastRun,
    Job,
    Membership,
    Plan,
    QuarantineItem,
    Source,
    Tenant,
    UsageEvent,
    User,
)
from ..services import freshness, results
from ..services.forecasting import service as fc
from ..storage import get_store
from .deps import rate_limited, read_upload

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(rate_limited)])


# ------------------------------------------------------------------ platform: sources & ingestion


class IngestIn(BaseModel):
    params: dict = {}


@router.post("/sources/{key}/ingest", status_code=202)
def trigger_ingest(
    key: str, body: IngestIn, db: Session = Depends(get_db), p: Principal = Depends(require("ingestion:run"))
) -> dict:
    s = db.scalar(select(Source).where(Source.key == key))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    if s.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": f"source is {s.status}", "reason": s.status_reason, "remediation": s.remediation},
        )
    job = queue.enqueue(
        db,
        "ingest",
        {"source_key": key, "params": body.params, "by": p.label},
        idempotency_key=f"manual:{key}:{uuid.uuid4().hex}",
    )
    audit.record_for(db, p, "ingestion.trigger", target_type="source", target_id=key, details={"job": str(job)})
    return {"job_id": str(job)}


@router.post("/sources/{key}/upload", status_code=202)
async def upload(
    key: str,
    request: Request,
    file: UploadFile = File(...),
    params: str = "{}",
    db: Session = Depends(get_db),
    p: Principal = Depends(require("ingestion:run")),
) -> dict:
    import json  # noqa: PLC0415

    s = db.scalar(select(Source).where(Source.key == key))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    if s.is_synthetic:
        raise HTTPException(status.HTTP_409_CONFLICT, "synthetic sources do not accept uploads")
    data = await read_upload(request, file)
    storage_key, digest = get_store().put(data, source_key=f"uploads/{key}")
    job = queue.enqueue(
        db,
        "ingest_upload",
        {
            "source_key": key,
            "storage_key": storage_key,
            "filename": file.filename,
            "params": json.loads(params),
            "by": p.label,
        },
        idempotency_key=f"upload:{key}:{digest}:{params}",
    )
    audit.record_for(
        db,
        p,
        "ingestion.upload",
        target_type="source",
        target_id=key,
        details={"sha256": digest, "filename": file.filename, "bytes": len(data)},
    )
    return {"job_id": str(job), "sha256": digest}


class SourceStatusIn(BaseModel):
    status: str = Field(pattern="^(active|pending_credentials|pending_license|network_blocked|unavailable|disabled)$")
    reason: str = Field(min_length=3)


@router.post("/sources/{key}/status")
def set_source_status(
    key: str, body: SourceStatusIn, db: Session = Depends(get_db), p: Principal = Depends(require("sources:manage"))
) -> dict:
    s = db.scalar(select(Source).where(Source.key == key))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    old = s.status
    s.status, s.status_reason = body.status, body.reason
    audit.record_for(
        db,
        p,
        "source.status",
        target_type="source",
        target_id=key,
        details={"from": old, "to": body.status, "reason": body.reason},
    )
    return {"key": key, "status": s.status}


@router.get("/quarantine")
def quarantine(
    status_: str = Query("open", alias="status"),
    source: str | None = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
    p: Principal = Depends(require("quarantine:review")),
) -> dict:
    q = select(QuarantineItem, Source.key).join(Source).where(QuarantineItem.status == status_)
    if source:
        q = q.where(Source.key == source)
    rows = db.execute(q.order_by(QuarantineItem.created_at.desc()).limit(limit)).all()
    return {
        "items": [
            {
                "id": str(i.id),
                "source": k,
                "run_id": str(i.run_id),
                "record_ref": i.record_ref,
                "rule": i.rule,
                "severity": i.severity,
                "message": i.message,
                "suggested_action": i.suggested_action,
                "payload": i.payload,
                "status": i.status,
                "created_at": i.created_at,
                "resolution_note": i.resolution_note,
            }
            for i, k in rows
        ],
        "counts": dict(
            db.execute(
                select(QuarantineItem.rule, func.count())
                .where(QuarantineItem.status == status_)
                .group_by(QuarantineItem.rule)
            ).all()
        ),
    }


class ResolveIn(BaseModel):
    resolution: str = Field(pattern="^(accepted|rejected|fixed)$")
    note: str = Field(min_length=5)


@router.post("/quarantine/{item_id}/resolve")
def resolve(
    item_id: uuid.UUID,
    body: ResolveIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require("quarantine:review")),
) -> dict:
    item = db.get(QuarantineItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    if item.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "item already resolved")
    item.status, item.resolution_note = body.resolution, body.note
    item.resolved_by, item.resolved_at = p.label, datetime.now(UTC)
    audit.record_for(
        db,
        p,
        "quarantine.resolve",
        target_type="quarantine_item",
        target_id=str(item_id),
        details={"resolution": body.resolution},
    )
    return {"id": str(item_id), "status": item.status}


@router.get("/jobs")
def jobs(
    status_: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    p: Principal = Depends(require("ops:read")),
) -> dict:
    q = select(Job).order_by(Job.created_at.desc()).limit(200)
    if status_:
        q = q.where(Job.status == status_)
    return {
        "counts": queue.refresh_gauges(db),
        "jobs": [
            {
                "id": str(j.id),
                "kind": j.kind,
                "status": j.status,
                "attempts": j.attempts,
                "max_attempts": j.max_attempts,
                "run_at": j.run_at,
                "last_error": (j.last_error or "")[:500],
                "created_at": j.created_at,
                "finished_at": j.finished_at,
                "result": j.result,
            }
            for j in db.scalars(q)
        ],
    }


@router.get("/jobs/{job_id}")
def job(job_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = Depends(require("data:read"))) -> dict:
    j = db.get(Job, job_id)
    if j is None or (j.tenant_id not in (None, p.tenant_id)) or (j.tenant_id is None and not p.has("ops:read")):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return {
        "id": str(j.id),
        "kind": j.kind,
        "status": j.status,
        "attempts": j.attempts,
        "result": j.result,
        "last_error": (j.last_error or "")[:500] if p.has("ops:read") else None,
    }


@router.post("/jobs/{job_id}/requeue")
def requeue(job_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = Depends(require("ingestion:run"))) -> dict:
    if not queue.requeue_dead(db, job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "only dead-lettered jobs can be requeued")
    audit.record_for(db, p, "job.requeue", target_type="job", target_id=str(job_id))
    return {"id": str(job_id), "status": "queued"}


@router.get("/ops/status")
def ops_status(db: Session = Depends(get_db), p: Principal = Depends(require("ops:read"))) -> dict:
    """Operational diagnostics. Contains no tenant research content."""
    return {
        "jobs": queue.refresh_gauges(db),
        "freshness": freshness.evaluate(db),
        "tenants": db.scalar(select(func.count()).select_from(Tenant)),
        "forecast_runs": dict(db.execute(select(ForecastRun.status, func.count()).group_by(ForecastRun.status)).all()),
    }


# ------------------------------------------------------------------ editorial: race calls


class RaceCallIn(BaseModel):
    candidacy_id: uuid.UUID
    caller_source_key: str = "editorial-desk"
    note: str = Field(min_length=10, description="Basis for the call under the editorial policy")
    retract: bool = False


@router.post("/contests/{contest_id}/race-calls", status_code=201)
def race_call(
    contest_id: uuid.UUID,
    body: RaceCallIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require("race_calls:record")),
) -> dict:
    if db.get(Contest, contest_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contest not found")
    try:
        rc = results.record_race_call(
            db,
            contest_id=contest_id,
            candidacy_id=body.candidacy_id,
            caller_source_key=body.caller_source_key,
            recorded_by=p.label,
            note=body.note,
            retract=body.retract,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    audit.record_for(
        db,
        p,
        "race_call.record",
        target_type="contest",
        target_id=str(contest_id),
        details={"candidacy": str(body.candidacy_id), "retract": body.retract},
    )
    return {"id": str(rc.id), "status": rc.status}


# ------------------------------------------------------------------ forecasts


class ForecastIn(BaseModel):
    country: str
    office: str
    cycle: int
    data_cutoff: str | None = None
    scenario: dict | None = None


@router.post("/forecasts", status_code=202)
def run_forecast(
    body: ForecastIn, db: Session = Depends(get_db), p: Principal = Depends(require("forecasts:run"))
) -> dict:
    job = queue.enqueue(
        db,
        "forecast_run",
        {**body.model_dump(), "by": p.label},
        idempotency_key=f"forecast:{uuid.uuid4().hex}",
        max_attempts=2,
    )
    audit.record_for(db, p, "forecast.run", target_type="job", target_id=str(job), details=body.model_dump())
    return {"job_id": str(job)}


@router.post("/forecasts/{run_id}/publish")
def publish_forecast(
    run_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = Depends(require("forecasts:publish"))
) -> dict:
    run = db.get(ForecastRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "forecast not found")
    try:
        fc.publish(db, run)
    except PermissionError as exc:
        audit.record_for(
            db,
            p,
            "forecast.publish",
            target_type="forecast_run",
            target_id=str(run_id),
            outcome="blocked",
            details={"reason": str(exc)},
        )
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": str(exc), "gates": run.gate_results}) from exc
    audit.record_for(db, p, "forecast.publish", target_type="forecast_run", target_id=str(run_id))
    return {"id": str(run_id), "status": run.status}


# ------------------------------------------------------------------ organization administration


class MemberIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|analyst|reviewer|viewer)$")


@router.get("/members")
def members(db: Session = Depends(get_db), p: Principal = Depends(require("tenant:admin"))) -> dict:
    rows = db.execute(
        select(User.id, User.email, User.display_name, Membership.role, User.last_seen_at)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.tenant_id == p.tenant_id)
    ).all()
    return {"members": [{"user_id": str(i), "email": e, "name": n, "role": r} for i, e, n, r, _ in rows]}


@router.post("/members", status_code=201)
def add_member(body: MemberIn, db: Session = Depends(get_db), p: Principal = Depends(require("tenant:admin"))) -> dict:
    tenant = db.get(Tenant, p.tenant_id)
    domains = (tenant.sso_config or {}).get("allowed_email_domains")
    if domains and body.email.split("@")[1].lower() not in domains:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "email domain not allowed by organization SSO policy")
    users = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).all()
    if len(users) != 1:
        # Invitations are delivered by the identity provider; the user must sign in once first.
        raise HTTPException(status.HTTP_409_CONFLICT, "user must sign in via SSO once before being added")
    m = db.get(Membership, {"tenant_id": p.tenant_id, "user_id": users[0].id})
    if m:
        m.role = body.role
    else:
        db.add(Membership(tenant_id=p.tenant_id, user_id=users[0].id, role=body.role))
    audit.record_for(
        db, p, "member.upsert", target_type="user", target_id=str(users[0].id), details={"role": body.role}
    )
    return {"user_id": str(users[0].id), "role": body.role}


@router.delete("/members/{user_id}")
def remove_member(
    user_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = Depends(require("tenant:admin"))
) -> dict:
    if user_id == p.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "admins cannot remove themselves")
    m = db.get(Membership, {"tenant_id": p.tenant_id, "user_id": user_id})
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")
    db.delete(m)
    audit.record_for(db, p, "member.remove", target_type="user", target_id=str(user_id))
    return {"removed": str(user_id)}


class TenantSettingsIn(BaseModel):
    publication_restrictions: dict | None = None
    data_retention_days: int | None = Field(None, ge=30, le=3650)
    sso_config: dict | None = None


@router.get("/tenant")
def tenant_settings(db: Session = Depends(get_db), p: Principal = Depends(require("tenant:admin"))) -> dict:
    t = db.get(Tenant, p.tenant_id)
    return {
        "slug": t.slug,
        "name": t.name,
        "plan": t.plan_key,
        "status": t.status,
        "home_region": t.home_region,
        "publication_restrictions": t.publication_restrictions,
        "data_retention_days": t.data_retention_days,
        "sso_config": t.sso_config,
    }


@router.patch("/tenant")
def update_tenant(
    body: TenantSettingsIn, db: Session = Depends(get_db), p: Principal = Depends(require("tenant:admin"))
) -> dict:
    t = db.get(Tenant, p.tenant_id)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(t, k, v)
    audit.record_for(
        db, p, "tenant.update", target_type="tenant", target_id=str(t.id), details={"fields": list(changes)}
    )
    return {"updated": list(changes)}


@router.get("/audit")
def audit_log(
    limit: int = Query(200, le=1000),
    action: str | None = None,
    db: Session = Depends(get_db),
    p: Principal = Depends(require("audit:read")),
) -> dict:
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)  # RLS restricts to this tenant
    if action:
        q = q.where(AuditEvent.action == action)
    return {
        "events": [
            {
                "id": e.id,
                "at": e.created_at,
                "actor": e.actor_label,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "outcome": e.outcome,
                "request_id": e.request_id,
                "details": e.details,
            }
            for e in db.scalars(q)
        ]
    }


@router.get("/usage")
def usage(db: Session = Depends(get_db), p: Principal = Depends(require("usage:read"))) -> dict:
    t = db.get(Tenant, p.tenant_id)
    plan = db.get(Plan, t.plan_key)
    used = dict(
        db.execute(
            select(UsageEvent.metric, func.sum(UsageEvent.quantity))
            .where(UsageEvent.tenant_id == p.tenant_id, UsageEvent.created_at >= entitlements.month_start())
            .group_by(UsageEvent.metric)
        ).all()
    )
    return {
        "plan": {"key": plan.key, "name": plan.name, "features": plan.features},
        "period_start": entitlements.month_start(),
        "metrics": {m: {"used": int(used.get(m, 0)), "limit": lim} for m, lim in plan.quotas.items()},
    }


@router.get("/billing")
def billing(p: Principal = Depends(require("tenant:admin"))) -> dict:
    return {
        "provider": None,
        "status": "not_configured",
        "detail": "No billing provider is integrated. Entitlements are assigned by plan; invoicing requires a "
        "product decision and provider credentials (see docs/operations/billing.md). No payments are "
        "simulated.",
    }
