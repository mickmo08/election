"""Source registry, immutable raw files, ingestion runs, quarantine and job queue."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, uuid_pk

SOURCE_STATUSES = (
    "active",  # ingesting successfully
    "pending_credentials",  # needs an API key / account
    "pending_license",  # needs a licence agreement before use
    "network_blocked",  # deployment cannot reach the host
    "unavailable",  # publisher offline / discontinued
    "disabled",  # turned off by an administrator
)

ACCESS_METHODS = ("api", "bulk_download", "licensed_feed", "manual_upload", "editorial", "synthetic_fixture")


class Source(Base):
    """A registered data source with ownership, access terms and licensing."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(f"status IN {SOURCE_STATUSES}", name="status"),
        CheckConstraint(f"access_method IN {ACCESS_METHODS}", name="access_method"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    publisher: Mapped[str] = mapped_column(String(300))
    owner_team: Mapped[str] = mapped_column(String(200))  # internal data owner
    homepage_url: Mapped[str] = mapped_column(Text)
    access_method: Mapped[str] = mapped_column(String(32))
    access_details: Mapped[str] = mapped_column(Text, default="")  # verified endpoint / file pattern
    access_terms: Mapped[str] = mapped_column(Text, default="")
    license: Mapped[str] = mapped_column(String(300), default="unknown")
    license_url: Mapped[str | None] = mapped_column(Text)
    permits_redistribution: Mapped[bool] = mapped_column(Boolean, default=False)
    permits_text_analysis: Mapped[bool] = mapped_column(Boolean, default=False)
    refresh_schedule: Mapped[str] = mapped_column(String(100), default="manual")  # cron or description
    freshness_sla_hours: Mapped[int | None] = mapped_column(Integer)
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)  # countries, offices, years
    reliability_notes: Mapped[str] = mapped_column(Text, default="")
    data_kind: Mapped[str] = mapped_column(String(64))  # official_results, campaign_finance, polls, boundaries, news...
    adapter_key: Mapped[str | None] = mapped_column(String(100))
    required_credentials: Mapped[list] = mapped_column(JSONB, default=list)  # env var names
    status: Mapped[str] = mapped_column(String(32), default="pending_credentials")
    status_reason: Mapped[str] = mapped_column(Text, default="")
    remediation: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    verification: Mapped[str] = mapped_column(Text, default="")  # how/when the access method was verified
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at = created_at()


class RawFile(Base):
    """An immutable retrieved artefact. Content is stored by SHA-256 in object storage."""

    __tablename__ = "raw_files"
    __table_args__ = (UniqueConstraint("source_id", "sha256"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(String(300))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(200))
    storage_key: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(64))
    http_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)  # etag, last-modified, status
    created_at = created_at()


RUN_STATUSES = ("running", "succeeded", "failed", "quarantined", "partial")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    adapter_key: Mapped[str] = mapped_column(String(100))
    adapter_version: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(300), index=True)
    raw_file_ids: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(32), default="running")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    checks: Mapped[list] = mapped_column(JSONB, default=list)  # data-quality check outcomes
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[str] = mapped_column(String(200), default="system")


QUARANTINE_STATUSES = ("open", "accepted", "rejected", "fixed")


class QuarantineItem(Base):
    __tablename__ = "quarantine_items"
    __table_args__ = (CheckConstraint(f"status IN {QUARANTINE_STATUSES}", name="status"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    raw_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_files.id"))
    record_ref: Mapped[str] = mapped_column(Text)  # e.g. "row 418"
    rule: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(16))  # error, warning
    message: Mapped[str] = mapped_column(Text)
    suggested_action: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolved_by: Mapped[str | None] = mapped_column(String(200))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at = created_at()


JOB_STATUSES = ("queued", "running", "succeeded", "failed", "dead")


class Job(Base):
    """Durable job queue on PostgreSQL (SELECT ... FOR UPDATE SKIP LOCKED).

    `failed` jobs are retried with exponential backoff until max_attempts; then they
    become `dead` (the dead-letter state) and require operator action to requeue.
    """

    __tablename__ = "jobs"
    __table_args__ = (CheckConstraint(f"status IN {JOB_STATUSES}", name="status"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    queue: Mapped[str] = mapped_column(String(64), default="default", index=True)
    kind: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(300), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    created_at = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
