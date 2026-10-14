"""Job handlers and the scheduler that enqueues due ingestion/maintenance work."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ingestion import adapters  # noqa: F401 - registers adapters
from .ingestion.framework import SourceUnavailable, run_ingestion
from .models import Source
from .queue import enqueue, handler
from .services import freshness, issues, retention


@handler("ingest")
def ingest(db: Session, payload: dict) -> dict:
    try:
        run = run_ingestion(db, payload["source_key"], payload.get("params"), triggered_by=payload.get("by", "queue"))
    except SourceUnavailable as exc:
        # Not retryable: recorded on the source and surfaced in the registry UI.
        return {"status": "unavailable", "reason": str(exc)}
    return {"run_id": str(run.id), "status": run.status}


@handler("ingest_upload")
def ingest_upload(db: Session, payload: dict) -> dict:
    from .ingestion.framework import FetchedFile  # noqa: PLC0415
    from .storage import get_store  # noqa: PLC0415

    content = get_store().get(payload["storage_key"])
    f = FetchedFile(url=f"upload://{payload.get('filename') or 'file'}", content=content,
                    content_type="application/octet-stream", filename=payload.get("filename"))
    run = run_ingestion(db, payload["source_key"], payload.get("params"), [f], triggered_by=payload.get("by", "upload"))
    if run.status in ("succeeded", "partial"):
        issues.classify_documents(db)
        db.commit()
    return {"run_id": str(run.id), "status": run.status, "stats": run.stats}


@handler("forecast_run")
def forecast_run(db: Session, payload: dict) -> dict:
    from datetime import date  # noqa: PLC0415

    from .services.forecasting import service as fc  # noqa: PLC0415

    run = fc.run_forecast(db, country=payload["country"], office_key=payload["office"],
                          cycle_year=int(payload["cycle"]),
                          data_cutoff=date.fromisoformat(payload["data_cutoff"]) if payload.get("data_cutoff") else None,
                          created_by=payload.get("by", "queue"), scenario=payload.get("scenario"))
    db.commit()
    return {"forecast_run_id": str(run.id), "status": run.status}


@handler("classify_documents")
def classify(db: Session, payload: dict) -> dict:
    return {"classified": issues.classify_documents(db)}


@handler("freshness_check")
def freshness_check(db: Session, payload: dict) -> dict:
    return freshness.evaluate(db)


@handler("retention_purge")
def retention_purge(db: Session, payload: dict) -> dict:
    return retention.purge_expired(db)


def schedule_due(db: Session) -> dict:
    """Enqueue one job per active automated source per hour (idempotency key = source+hour)."""
    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    queued = []
    for s in db.scalars(select(Source).where(Source.status == "active", Source.access_method.in_(["api", "bulk_download",
                                                                                                    "licensed_feed"]))):
        if enqueue(db, "ingest", {"source_key": s.key, "by": "scheduler"}, idempotency_key=f"ingest:{s.key}:{hour}"):
            queued.append(s.key)
    enqueue(db, "freshness_check", {}, idempotency_key=f"freshness:{hour}")
    enqueue(db, "classify_documents", {}, idempotency_key=f"classify:{hour}")
    enqueue(db, "retention_purge", {}, idempotency_key=f"retention:{hour[:8]}")
    return {"ingest": queued}
