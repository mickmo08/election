"""Retention and deletion.

* Per-tenant retention (tenant.data_retention_days) for assistant query logs and export records.
* Tenant hard deletion (purge_tenant) runs as the schema owner per the offboarding runbook,
  because published report versions and audit events are otherwise immutable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from ..models import (
    AssistantQuery,
    Export,
    Membership,
    Poll,
    PollQuestion,
    PollResult,
    Report,
    ReportVersion,
    SurveyDataset,
    SurveyResponse,
    Tenant,
    UsageEvent,
)


def purge_expired(db: Session) -> dict:
    counts = {}
    for t in db.scalars(select(Tenant)):
        cutoff = datetime.now(UTC) - timedelta(days=t.data_retention_days)
        for model in (AssistantQuery, Export):
            res = db.execute(delete(model).where(model.tenant_id == t.id, model.created_at < cutoff))
            counts[f"{t.slug}:{model.__tablename__}"] = res.rowcount  # type: ignore[attr-defined]
        res = db.execute(delete(UsageEvent).where(UsageEvent.tenant_id == t.id,
                                                  UsageEvent.created_at < datetime.now(UTC) - timedelta(days=800)))
        counts[f"{t.slug}:usage_events"] = res.rowcount  # type: ignore[attr-defined]
    return counts


def purge_tenant(db: Session, tenant_id: uuid.UUID) -> dict:
    """Irreversibly delete a tenant's research data. Requires the schema-owner connection."""
    db.execute(text("SELECT set_config('app.retention_purge', 'on', true)"))
    out = {}
    out["survey_responses"] = db.execute(delete(SurveyResponse).where(SurveyResponse.tenant_id == tenant_id)).rowcount  # type: ignore[attr-defined]
    out["survey_datasets"] = db.execute(delete(SurveyDataset).where(SurveyDataset.tenant_id == tenant_id)).rowcount  # type: ignore[attr-defined]
    out["report_versions"] = db.execute(delete(ReportVersion).where(ReportVersion.tenant_id == tenant_id)).rowcount  # type: ignore[attr-defined]
    out["reports"] = db.execute(delete(Report).where(Report.tenant_id == tenant_id)).rowcount  # type: ignore[attr-defined]
    poll_ids = select(Poll.id).where(Poll.tenant_id == tenant_id)
    q_ids = select(PollQuestion.id).where(PollQuestion.poll_id.in_(poll_ids))
    db.execute(delete(PollResult).where(PollResult.question_id.in_(q_ids)))
    db.execute(delete(PollQuestion).where(PollQuestion.poll_id.in_(poll_ids)))
    out["polls"] = db.execute(delete(Poll).where(Poll.tenant_id == tenant_id)).rowcount  # type: ignore[attr-defined]
    for model in (AssistantQuery, Export, UsageEvent):
        out[model.__tablename__] = db.execute(delete(model).where(model.tenant_id == tenant_id)).rowcount  # type: ignore[attr-defined]
    db.execute(delete(Membership).where(Membership.tenant_id == tenant_id))
    t = db.get(Tenant, tenant_id)
    if t:
        t.status = "deleted"
    return out
