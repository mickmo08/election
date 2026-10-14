"""Durable PostgreSQL-backed job queue with retries, backoff and dead-lettering."""

from __future__ import annotations

import logging
import socket
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .models import Job
from .observability import JOBS_DEAD, JOBS_PROCESSED, JOBS_QUEUED, log

logger = logging.getLogger("queue")
WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
HANDLERS: dict[str, Callable[[Session, dict], dict | None]] = {}
LEASE = timedelta(minutes=15)


def handler(kind: str):  # type: ignore[no-untyped-def]
    def deco(fn):  # type: ignore[no-untyped-def]
        HANDLERS[kind] = fn
        return fn
    return deco


def enqueue(db: Session, kind: str, payload: dict, *, idempotency_key: str | None = None,
            queue: str = "default", max_attempts: int = 5, run_at: datetime | None = None,
            tenant_id: uuid.UUID | None = None) -> uuid.UUID | None:
    """Insert a job. With an idempotency key, a duplicate enqueue is a no-op returning the existing id."""
    stmt = insert(Job).values(
        id=uuid.uuid4(), queue=queue, kind=kind, payload=payload, idempotency_key=idempotency_key,
        status="queued", attempts=0, max_attempts=max_attempts, run_at=run_at or datetime.now(UTC),
        tenant_id=tenant_id,
    )
    if idempotency_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])
    res = db.execute(stmt.returning(Job.id)).scalar()
    if res is None and idempotency_key:
        res = db.scalar(select(Job.id).where(Job.idempotency_key == idempotency_key))
    return res


def backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(3600, 15 * 2 ** (attempt - 1)))


def claim(db: Session, queue: str = "default") -> Job | None:
    now = datetime.now(UTC)
    job = db.scalar(
        select(Job).where(
            Job.queue == queue,
            ((Job.status.in_(["queued", "failed"])) & (Job.run_at <= now))
            # Recover jobs whose worker died mid-run (lease expired).
            | ((Job.status == "running") & (Job.heartbeat_at < now - LEASE)),
        ).order_by(Job.run_at).limit(1).with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status, job.locked_by, job.locked_at, job.heartbeat_at = "running", WORKER_ID, now, now
    job.attempts += 1
    db.commit()
    return job


def run_one(db: Session, queue: str = "default") -> bool:
    job = claim(db, queue)
    if job is None:
        return False
    fn = HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise LookupError(f"no handler registered for job kind {job.kind!r}")
        result = fn(db, job.payload)
        db.commit()
        db.execute(update(Job).where(Job.id == job.id).values(
            status="succeeded", result=result or {}, finished_at=datetime.now(UTC), last_error=None))
        db.commit()
        JOBS_PROCESSED.labels(job.kind, "succeeded").inc()
        log(logger, logging.INFO, "job succeeded", job_id=str(job.id), kind=job.kind, attempts=job.attempts)
    except Exception as exc:  # noqa: BLE001 - any handler failure is recorded and retried
        db.rollback()
        dead = job.attempts >= job.max_attempts
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"[:8000]
        db.execute(update(Job).where(Job.id == job.id).values(
            status="dead" if dead else "failed", last_error=err,
            run_at=datetime.now(UTC) + backoff(job.attempts),
            finished_at=datetime.now(UTC) if dead else None))
        db.commit()
        JOBS_PROCESSED.labels(job.kind, "dead" if dead else "failed").inc()
        log(logger, logging.ERROR if dead else logging.WARNING, "job failed", job_id=str(job.id),
            kind=job.kind, attempts=job.attempts, dead=dead, error=str(exc))
    return True


def requeue_dead(db: Session, job_id: uuid.UUID, reset_attempts: bool = True) -> bool:
    res = db.execute(update(Job).where(Job.id == job_id, Job.status == "dead").values(
        status="queued", run_at=datetime.now(UTC), attempts=0 if reset_attempts else Job.attempts,
        finished_at=None))
    return res.rowcount == 1  # type: ignore[attr-defined]


def refresh_gauges(db: Session) -> dict:
    rows = db.execute(text("SELECT status, count(*) FROM jobs GROUP BY status")).all()
    counts = {r[0]: r[1] for r in rows}
    JOBS_DEAD.set(counts.get("dead", 0))
    JOBS_QUEUED.set(counts.get("queued", 0) + counts.get("failed", 0))
    return counts
