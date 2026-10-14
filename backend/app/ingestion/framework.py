"""Ingestion pipeline: fetch -> store immutable raw -> parse -> validate -> quarantine -> load.

Guarantees
  * Raw artefacts are stored once, content-addressed, with URL/publisher/time/hash/schema.
  * Runs are idempotent: identical inputs (source, adapter version, params, file hashes)
    short-circuit to the previous successful run.
  * Loads are transactional: a run whose file fails structural validation loads nothing
    and is marked `quarantined`; record-level failures are quarantined individually and
    the remaining records load (`partial`).
  * Every loaded row carries source_id and ingestion_run_id for lineage.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import IngestionRun, QuarantineItem, RawFile, Source
from ..observability import INGESTION_RUNS, log
from ..storage import RawStore, get_store

logger = logging.getLogger("ingestion")


class SourceUnavailable(Exception):
    """The source cannot be reached or is not configured. Not retried automatically."""


class TransientSourceError(Exception):
    """Temporary upstream failure (timeout, 5xx). The job is retried with backoff."""


@dataclass
class FetchedFile:
    url: str
    content: bytes
    content_type: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    http_metadata: dict = field(default_factory=dict)
    filename: str | None = None


@dataclass
class Issue:
    record_ref: str
    rule: str
    message: str
    severity: str = "error"  # error | warning
    suggested_action: str = ""
    payload: dict = field(default_factory=dict)
    blocking: bool = False  # True => whole file rejected, nothing loaded


class StructuralError(Exception):
    def __init__(self, issues: list[Issue]):
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues


@dataclass
class RunContext:
    db: Session
    source: Source
    run: IngestionRun
    params: dict
    raw_files: dict[str, RawFile]  # sha256 -> RawFile
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)

    def quarantine(self, issue: Issue) -> None:
        self.issues.append(issue)

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "passed": passed, "detail": detail})

    def raw_file_for(self, f: FetchedFile) -> RawFile:
        return self.raw_files[hashlib.sha256(f.content).hexdigest()]


class SourceAdapter(ABC):
    key: str
    version: str
    schema_version: str

    def fetch(self, source: Source, params: dict) -> list[FetchedFile]:
        raise SourceUnavailable(
            f"{source.key} has no automated fetch; upload the file manually. {source.remediation}".strip())

    @abstractmethod
    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        """Parse, validate and load. Raise StructuralError to reject the whole run."""


ADAPTERS: dict[str, SourceAdapter] = {}


def register(adapter: SourceAdapter) -> SourceAdapter:
    ADAPTERS[adapter.key] = adapter
    return adapter


def _idempotency_key(source_key: str, adapter: SourceAdapter, params: dict, hashes: list[str]) -> str:
    material = json.dumps([source_key, adapter.key, adapter.version, params, sorted(hashes)], sort_keys=True,
                          default=str)
    return hashlib.sha256(material.encode()).hexdigest()


def store_raw(db: Session, store: RawStore, source: Source, f: FetchedFile, schema_version: str) -> RawFile:
    key, digest = store.put(f.content, source_key=source.key)
    db.execute(insert(RawFile).values(
        id=uuid.uuid4(), source_id=source.id, url=f.url, publisher=source.publisher, retrieved_at=f.retrieved_at,
        sha256=digest, size_bytes=len(f.content), content_type=f.content_type, storage_key=key,
        schema_version=schema_version, http_metadata=f.http_metadata | ({"filename": f.filename} if f.filename else {}),
    ).on_conflict_do_nothing(index_elements=["source_id", "sha256"]))
    return db.scalar(select(RawFile).where(RawFile.source_id == source.id, RawFile.sha256 == digest))


def run_ingestion(db: Session, source_key: str, params: dict | None = None, files: list[FetchedFile] | None = None,
                  triggered_by: str = "system", store: RawStore | None = None) -> IngestionRun:
    params = params or {}
    source = db.scalar(select(Source).where(Source.key == source_key))
    if source is None:
        raise LookupError(f"unknown source {source_key!r}")
    if source.is_synthetic and not get_settings().allows_synthetic_data:
        raise PermissionError("synthetic sources are disabled in this environment")
    if not source.adapter_key or source.adapter_key not in ADAPTERS:
        raise SourceUnavailable(f"source {source_key} has no implemented adapter. {source.remediation}")
    adapter = ADAPTERS[source.adapter_key]
    source.last_attempt_at = datetime.now(UTC)
    now = datetime.now(UTC)

    if files is None:
        if source.status not in ("active",):
            run = IngestionRun(source_id=source.id, adapter_key=adapter.key, adapter_version=adapter.version,
                               params=params, idempotency_key="unavailable:" + uuid.uuid4().hex, status="failed",
                               error=f"source status is {source.status}: {source.status_reason}",
                               started_at=now, finished_at=now, triggered_by=triggered_by)
            db.add(run)
            db.commit()
            INGESTION_RUNS.labels(source.key, "failed").inc()
            raise SourceUnavailable(run.error + (" Remediation: " + source.remediation if source.remediation else ""))
        files = adapter.fetch(source, params)

    store = store or get_store()
    raw = {}
    for f in files:
        rf = store_raw(db, store, source, f, adapter.schema_version)
        raw[rf.sha256] = rf
    idem = _idempotency_key(source.key, adapter, params, list(raw))
    previous = db.scalar(select(IngestionRun).where(
        IngestionRun.idempotency_key == idem, IngestionRun.status.in_(["succeeded", "partial"])))
    if previous is not None:
        db.commit()
        log(logger, logging.INFO, "ingestion skipped (idempotent)", source=source.key, run_id=str(previous.id))
        return previous

    run = IngestionRun(source_id=source.id, adapter_key=adapter.key, adapter_version=adapter.version, params=params,
                       idempotency_key=idem, raw_file_ids=[str(r.id) for r in raw.values()], status="running",
                       started_at=now, triggered_by=triggered_by)
    db.add(run)
    db.commit()  # the run is visible to operators while processing

    ctx = RunContext(db=db, source=source, run=run, params=params, raw_files=raw)
    savepoint = db.begin_nested()
    try:
        adapter.process(ctx, files)
        savepoint.commit()
        record_errors = [i for i in ctx.issues if i.severity == "error"]
        run.status = "partial" if record_errors else "succeeded"
    except StructuralError as exc:
        savepoint.rollback()
        ctx.issues.extend(exc.issues)
        run.status = "quarantined"
    except Exception as exc:
        savepoint.rollback()
        run.status, run.error, run.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:4000], datetime.now(UTC)
        run.stats, run.checks = ctx.stats, ctx.checks
        db.commit()
        INGESTION_RUNS.labels(source.key, "failed").inc()
        raise
    first_raw = next(iter(raw.values()), None)
    for issue in ctx.issues:
        db.add(QuarantineItem(
            run_id=run.id, source_id=source.id, raw_file_id=first_raw.id if first_raw else None,
            record_ref=issue.record_ref, rule=issue.rule, severity=issue.severity, message=issue.message,
            suggested_action=issue.suggested_action, payload=issue.payload,
            status="open" if issue.severity == "error" else "accepted"))
    run.stats, run.checks, run.finished_at = ctx.stats, ctx.checks, datetime.now(UTC)
    if run.status in ("succeeded", "partial"):
        source.last_success_at = run.finished_at
    db.commit()
    INGESTION_RUNS.labels(source.key, run.status).inc()
    log(logger, logging.INFO, "ingestion finished", source=source.key, run_id=str(run.id), status=run.status,
        stats=ctx.stats, issues=len(ctx.issues))
    return run
