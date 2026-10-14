"""Operational CLI: python -m app.cli <command>."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .observability import configure_logging


def _owner_session() -> Session:
    from .db import make_engine  # noqa: PLC0415

    return Session(make_engine(get_settings().migration_database_url))


def cmd_sync_reference(args: argparse.Namespace) -> None:
    from .services.reference import sync_all  # noqa: PLC0415

    with _owner_session() as db:
        sync_all(db, include_synthetic=args.synthetic)
        db.commit()
    print("reference data synchronised")


def cmd_ingest(args: argparse.Namespace) -> None:
    from . import ingestion  # noqa: F401,PLC0415
    from .ingestion import adapters  # noqa: F401,PLC0415
    from .ingestion.framework import FetchedFile, run_ingestion  # noqa: PLC0415

    files = None
    if args.file:
        p = Path(args.file)
        files = [FetchedFile(url=args.url or f"upload://{p.name}", content=p.read_bytes(),
                             content_type="application/octet-stream", filename=p.name)]
    from .db import worker_session  # noqa: PLC0415

    with worker_session() as db:
        run = run_ingestion(db, args.source, json.loads(args.params or "{}"), files, triggered_by="cli")
        print(json.dumps({"run_id": str(run.id), "status": run.status, "stats": run.stats}, default=str))


def cmd_seed_demo(args: argparse.Namespace) -> None:
    """Create demo tenants/users (development and staging only) and load synthetic data."""
    s = get_settings()
    if not s.allows_synthetic_data:
        sys.exit("refusing: synthetic demo data is disabled in this environment")
    from .db import worker_session  # noqa: PLC0415
    from .ingestion import adapters  # noqa: F401,PLC0415
    from .ingestion.framework import run_ingestion  # noqa: PLC0415
    from .models import Membership, Tenant, User  # noqa: PLC0415
    from .services.issues import classify_documents  # noqa: PLC0415
    from .services.reference import sync_all  # noqa: PLC0415

    with _owner_session() as db:
        sync_all(db, include_synthetic=True)
        db.commit()
    with worker_session() as db:
        run = run_ingestion(db, "xs-synthetic", {"seed": 7}, triggered_by="seed-demo")
        print("synthetic run:", run.status, run.stats)
        classify_documents(db)
        for slug, name, plan in (("demo-newsroom", "Demo Newsroom (synthetic)", "newsroom"),
                                 ("demo-university", "Demo University Lab (synthetic)", "research")):
            if db.scalar(select(Tenant).where(Tenant.slug == slug)) is None:
                db.add(Tenant(id=uuid.uuid4(), slug=slug, name=name, plan_key=plan))
        db.flush()
        users = [("demo-admin", "admin@demo.invalid", "demo-newsroom", "admin", True),
                 ("demo-analyst", "analyst@demo.invalid", "demo-newsroom", "analyst", False),
                 ("demo-reviewer", "reviewer@demo.invalid", "demo-newsroom", "reviewer", False),
                 ("demo-viewer", "viewer@demo.invalid", "demo-newsroom", "viewer", False),
                 ("uni-analyst", "analyst@uni.invalid", "demo-university", "analyst", False)]
        for sub, email, slug, role, op in users:
            u = db.scalar(select(User).where(User.issuer == "election-dev", User.subject == sub))
            if u is None:
                u = User(issuer="election-dev", subject=sub, email=email, display_name=email, is_platform_operator=op)
                db.add(u)
                db.flush()
            t = db.scalar(select(Tenant).where(Tenant.slug == slug))
            if db.get(Membership, {"tenant_id": t.id, "user_id": u.id}) is None:
                db.add(Membership(tenant_id=t.id, user_id=u.id, role=role))
        db.commit()
    print("demo tenants and users ready (dev tokens: POST /api/v1/dev/token)")


def cmd_worker(args: argparse.Namespace) -> None:
    from . import jobs  # noqa: F401,PLC0415 - registers handlers
    from .db import worker_session  # noqa: PLC0415
    from .queue import refresh_gauges, run_one  # noqa: PLC0415

    print("worker started", flush=True)
    last_gauge = 0.0
    while True:
        with worker_session() as db:
            worked = run_one(db, args.queue)
            if time.monotonic() - last_gauge > 30:
                refresh_gauges(db)
                last_gauge = time.monotonic()
        if args.once and not worked:
            return
        if not worked:
            time.sleep(args.poll_interval)


def cmd_scheduler(args: argparse.Namespace) -> None:
    from . import jobs  # noqa: PLC0415
    from .db import worker_session  # noqa: PLC0415

    with worker_session() as db:
        print(json.dumps(jobs.schedule_due(db), default=str))
        db.commit()


def main() -> None:
    configure_logging(get_settings().log_level)
    p = argparse.ArgumentParser(prog="election")
    sub = p.add_subparsers(required=True)
    s = sub.add_parser("sync-reference")
    s.add_argument("--synthetic", action=argparse.BooleanOptionalAction, default=None)
    s.set_defaults(fn=cmd_sync_reference)
    s = sub.add_parser("ingest")
    s.add_argument("source")
    s.add_argument("--file")
    s.add_argument("--url")
    s.add_argument("--params")
    s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("seed-demo")
    s.set_defaults(fn=cmd_seed_demo)
    s = sub.add_parser("worker")
    s.add_argument("--queue", default="default")
    s.add_argument("--once", action="store_true")
    s.add_argument("--poll-interval", type=float, default=2.0)
    s.set_defaults(fn=cmd_worker)
    s = sub.add_parser("schedule")
    s.set_defaults(fn=cmd_scheduler)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
