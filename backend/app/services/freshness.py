"""Data freshness and data-quality monitoring."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import QuarantineItem, Source
from ..observability import QUARANTINE_OPEN, SOURCE_STALE, SOURCE_STALENESS, log

logger = logging.getLogger("freshness")


def source_freshness(source: Source, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    age_h = (now - source.last_success_at).total_seconds() / 3600 if source.last_success_at else None
    if source.status != "active":
        state = "unavailable"
    elif source.freshness_sla_hours is None:
        state = "no_sla"
    elif age_h is None:
        state = "never_loaded"
    elif age_h > source.freshness_sla_hours:
        state = "stale"
    else:
        state = "fresh"
    return {
        "source": source.key,
        "state": state,
        "age_hours": round(age_h, 2) if age_h is not None else None,
        "sla_hours": source.freshness_sla_hours,
        "last_success_at": source.last_success_at,
        "status": source.status,
    }


def evaluate(db: Session) -> dict:
    out = []
    for s in db.scalars(select(Source)):
        f = source_freshness(s)
        if f["age_hours"] is not None:
            SOURCE_STALENESS.labels(s.key).set(f["age_hours"])
        breached = f["state"] in ("stale", "never_loaded")
        SOURCE_STALE.labels(s.key).set(1 if breached else 0)
        if breached:
            log(logger, logging.WARNING, "freshness breach", source=s.key, state=f["state"], age_hours=f["age_hours"])
        out.append(f)
    open_items = db.scalar(select(func.count()).select_from(QuarantineItem).where(QuarantineItem.status == "open"))
    QUARANTINE_OPEN.set(open_items or 0)
    return {
        "sources": out,
        "quarantine_open": open_items,
        "breaches": [f["source"] for f in out if f["state"] in ("stale", "never_loaded")],
    }
