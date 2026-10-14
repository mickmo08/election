"""Test configuration: a dedicated database, real RLS roles, synthetic seed loaded once."""

from __future__ import annotations

import os
import tempfile

os.environ.update(
    {
        "ELECTION_ENVIRONMENT": "test",
        "ELECTION_DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://election_app:election_app@localhost:5432/election_test"
        ),
        "ELECTION_WORKER_DATABASE_URL": os.environ.get(
            "TEST_WORKER_DATABASE_URL",
            "postgresql+psycopg://election_worker:election_worker@localhost:5432/election_test",
        ),
        "ELECTION_MIGRATION_DATABASE_URL": os.environ.get(
            "TEST_MIGRATION_DATABASE_URL", "postgresql+psycopg://election:election@localhost:5432/election_test"
        ),
        "ELECTION_DEV_AUTH_SECRET": "test-secret-0123456789abcdef0123456789abcdef",
        "ELECTION_STORAGE_LOCAL_PATH": tempfile.mkdtemp(prefix="election-raw-"),
        "ELECTION_RATE_LIMIT_PER_MINUTE": "100000",
        "ELECTION_ASSISTANT_RATE_LIMIT_PER_MINUTE": "100000",
        "ELECTION_LOG_LEVEL": "WARNING",
    }
)

import uuid  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import make_engine, worker_session  # noqa: E402

HERE = os.path.dirname(__file__)


def owner_engine():
    return make_engine(get_settings().migration_database_url)


def reset_schema() -> None:
    eng = owner_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT USAGE ON SCHEMA public TO PUBLIC"))
    eng.dispose()
    cfg = Config(os.path.join(HERE, "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(HERE, "..", "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().migration_database_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def database():
    reset_schema()
    from app.cli import cmd_seed_demo  # noqa: PLC0415

    cmd_seed_demo(None)  # type: ignore[arg-type]
    yield


@pytest.fixture
def owner_db():
    with Session(owner_engine()) as s:
        yield s
        s.rollback()


@pytest.fixture
def wdb():
    with worker_session() as s:
        yield s
        s.rollback()


@pytest.fixture(scope="session")
def client(database):
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from app.main import app  # noqa: PLC0415

    return TestClient(app)


def token_for(client, subject: str) -> str:
    r = client.post("/api/v1/dev/token", json={"subject": subject})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def headers(client):
    cache: dict[str, dict] = {}

    def make(subject: str, tenant: str = "demo-newsroom") -> dict:
        if subject not in cache:
            cache[subject] = {"authorization": f"Bearer {token_for(client, subject)}"}
        return {**cache[subject], "x-tenant": tenant}

    return make


@pytest.fixture(scope="session")
def tenants(database):
    from app.models import Tenant, User  # noqa: PLC0415

    with worker_session() as s:
        t = {x.slug: x.id for x in s.scalars(select(Tenant))}
        u = {x.subject: x.id for x in s.scalars(select(User))}
    return t, u


def make_user(subject: str, tenant_slug: str, role: str, operator: bool = False) -> uuid.UUID:
    from app.models import Membership, Tenant, User  # noqa: PLC0415

    with worker_session() as s:
        u = s.scalar(select(User).where(User.subject == subject))
        if u is None:
            u = User(
                issuer="election-dev", subject=subject, email=f"{subject}@test.invalid", is_platform_operator=operator
            )
            s.add(u)
            s.flush()
        t = s.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if s.get(Membership, {"tenant_id": t.id, "user_id": u.id}) is None:
            s.add(Membership(tenant_id=t.id, user_id=u.id, role=role))
        s.commit()
        return u.id
