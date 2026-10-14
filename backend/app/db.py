"""Database engines and tenant-scoped sessions.

Three roles are used (see docs/security/tenant-isolation.md):
  * election_app     - API runtime, subject to row-level security (RLS)
  * election_worker  - background jobs, BYPASSRLS, never reachable from request handlers
  * election (owner) - migrations and ops tooling only
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def _json_default(o: object) -> object:
    if isinstance(o, datetime | date):
        return o.isoformat()
    if isinstance(o, uuid.UUID | Decimal):
        return str(o)
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def json_dumps(o: object) -> str:
    return json.dumps(o, default=_json_default)


def make_engine(url: str, **kw: object) -> Engine:
    return create_engine(url, json_serializer=json_dumps, pool_pre_ping=True, **kw)


@lru_cache
def app_engine() -> Engine:
    return make_engine(get_settings().database_url, pool_size=10, max_overflow=10)


@lru_cache
def worker_engine() -> Engine:
    return make_engine(get_settings().worker_database_url, pool_size=5)


def set_tenant(session: Session, tenant_id: uuid.UUID | None) -> None:
    """Bind the RLS tenant context for the current transaction only (SET LOCAL semantics)."""
    session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id) if tenant_id else ""},
    )


@contextmanager
def tenant_session(tenant_id: uuid.UUID | None) -> Iterator[Session]:
    factory = sessionmaker(app_engine(), expire_on_commit=False)
    with factory() as session, session.begin():
        set_tenant(session, tenant_id)
        yield session


@contextmanager
def worker_session() -> Iterator[Session]:
    factory = sessionmaker(worker_engine(), expire_on_commit=False)
    with factory() as session:
        yield session
