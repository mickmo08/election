"""Subscription entitlements, quotas and usage metering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Plan, Tenant, UsageEvent

DEFAULT_PLANS = [
    {
        "key": "research",
        "name": "Research",
        "quotas": {"ai_queries": 500, "imports": 50, "exports": 200, "storage_bytes": 5 * 1024**3},
        "features": ["explorer", "polling", "issues", "forecasts", "assistant", "reports"],
    },
    {
        "key": "newsroom",
        "name": "Newsroom",
        "quotas": {"ai_queries": 5000, "imports": 500, "exports": 2000, "storage_bytes": 50 * 1024**3},
        "features": ["explorer", "polling", "issues", "forecasts", "assistant", "reports", "results_monitoring"],
    },
    {
        "key": "trial",
        "name": "Trial",
        "quotas": {"ai_queries": 50, "imports": 5, "exports": 20, "storage_bytes": 512 * 1024**2},
        "features": ["explorer", "polling", "forecasts", "assistant"],
    },
]


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage_this_month(db: Session, tenant_id: uuid.UUID, metric: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.tenant_id == tenant_id, UsageEvent.metric == metric, UsageEvent.created_at >= month_start()
            )
        )
        or 0
    )


def check_and_meter(
    db: Session, tenant_id: uuid.UUID, metric: str, quantity: int = 1, details: dict | None = None
) -> None:
    """Raise 402/403 if the quota would be exceeded; otherwise record usage atomically."""
    tenant = db.get(Tenant, tenant_id)
    plan = db.get(Plan, tenant.plan_key) if tenant else None
    if plan is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no active plan")
    # Serialise quota checks per tenant+metric to prevent concurrent overruns.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"{tenant_id}:{metric}"))))
    limit = plan.quotas.get(metric)
    if limit is not None and usage_this_month(db, tenant_id, metric) + quantity > limit:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, f"monthly {metric} quota of {limit} reached")
    db.add(UsageEvent(tenant_id=tenant_id, metric=metric, quantity=quantity, details=details or {}))


def has_feature(db: Session, tenant_id: uuid.UUID, feature: str) -> bool:
    tenant = db.get(Tenant, tenant_id)
    plan = db.get(Plan, tenant.plan_key) if tenant else None
    return bool(plan and feature in plan.features)
