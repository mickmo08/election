"""Audit trail helpers. Events record who did what to which object; never research content."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .models import AuditEvent
from .observability import request_id_var


def record(
    db: Session,
    action: str,
    *,
    actor_label: str,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: str = "success",
    ip: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_label=actor_label,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            ip=ip,
            request_id=request_id_var.get(),
            details=details or {},
        )
    )


def record_for(db: Session, p, action: str, **kw) -> None:  # type: ignore[no-untyped-def]
    record(db, action, actor_label=p.label, tenant_id=p.tenant_id, actor_user_id=p.user_id, **kw)
