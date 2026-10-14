from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..auth import Principal, get_db, issue_dev_token, principal
from ..config import get_settings
from ..models import Membership, Tenant, User

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz(db: Session = Depends(get_db)) -> dict:
    try:
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    return {"status": "ready", "schema_version": version}


@router.get("/metrics", include_in_schema=False)
def metrics(x_metrics_token: str | None = Header(default=None)) -> Response:
    # Metrics are also blocked at the load balancer; the token is defence in depth.
    import os  # noqa: PLC0415

    expected = os.environ.get("ELECTION_METRICS_TOKEN")
    if expected and x_metrics_token != expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class DevTokenIn(BaseModel):
    subject: str


@router.post("/api/v1/dev/token", include_in_schema=False)
def dev_token(body: DevTokenIn, db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    if s.environment not in ("development", "test") or not s.dev_auth_secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    user = db.scalar(select(User).where(User.issuer == "election-dev", User.subject == body.subject))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown demo user")
    memberships = db.execute(select(Tenant.slug, Membership.role).join(Membership, Membership.tenant_id == Tenant.id)
                             .where(Membership.user_id == user.id)).all()
    return {"token": issue_dev_token(body.subject, user.email or ""), "tenants": [
        {"slug": t, "role": r} for t, r in memberships]}


@router.get("/api/v1/me")
def me(p: Principal = Depends(principal), db: Session = Depends(get_db)) -> dict:
    tenants = db.execute(select(Tenant.slug, Tenant.name, Membership.role).join(
        Membership, Membership.tenant_id == Tenant.id).where(Membership.user_id == p.user_id)).all()
    return {"user": p.label, "tenant": p.tenant_slug, "role": p.role, "is_operator": p.is_operator,
            "permissions": sorted(p.permissions),
            "tenants": [{"slug": s, "name": n, "role": r} for s, n, r in tenants],
            "environment": get_settings().environment}
