"""Organisations, users, roles, audit trail, entitlements and usage metering."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, uuid_pk

ROLES = ("admin", "analyst", "reviewer", "viewer")


class Plan(Base):
    """Configurable subscription entitlements. Prices live in the billing provider, not here."""

    __tablename__ = "plans"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    quotas: Mapped[dict] = mapped_column(JSONB, default=dict)  # metric -> monthly limit
    features: Mapped[list] = mapped_column(JSONB, default=list)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    plan_key: Mapped[str] = mapped_column(ForeignKey("plans.key"))
    status: Mapped[str] = mapped_column(String(32), default="active")  # active, suspended, deleted
    home_region: Mapped[str] = mapped_column(String(32), default="us")
    # e.g. {"blocked_countries_for_poll_publication": ["FR"], "embargo_until": ...}
    publication_restrictions: Mapped[dict] = mapped_column(JSONB, default=dict)
    data_retention_days: Mapped[int] = mapped_column(Integer, default=730)
    sso_config: Mapped[dict] = mapped_column(JSONB, default=dict)  # issuer, allowed domains
    billing_customer_ref: Mapped[str | None] = mapped_column(String(200))
    created_at = created_at()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(300))
    is_platform_operator: Mapped[bool] = mapped_column(default=False)
    created_at = created_at()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="role"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    created_at = created_at()


class AuditEvent(Base):
    """Append-only (enforced by trigger). Never stores research content, only references."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(300))
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str | None] = mapped_column(String(100))
    target_id: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(32), default="success")
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(INET)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at = created_at()


METRICS = ("ai_queries", "imports", "exports", "storage_bytes", "api_requests")


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (CheckConstraint(f"metric IN {METRICS}", name="metric"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    metric: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(BigInteger)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at = created_at()


class Export(Base):
    __tablename__ = "exports"
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    dataset: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    row_count: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at = created_at()
