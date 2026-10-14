"""Authentication (OIDC bearer tokens) and role-based authorization.

Production accepts only asymmetric (RS*/ES*) tokens from the configured OIDC issuer,
validated against its JWKS. Enterprise SSO is supported by federating customer IdPs
through that issuer and restricting tenants to an issuer/email domain (tenant.sso_config).
HS256 "dev tokens" exist only for development and automated tests and are refused
when ELECTION_ENVIRONMENT is staging or production (enforced in config validation too).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import set_tenant
from .models import Membership, Tenant, User
from .observability import AUTHZ_DENIALS, tenant_var

PERMISSIONS: dict[str, set[str]] = {
    "viewer": {"data:read", "reports:read_published", "forecasts:read"},
    "analyst": {
        "data:read", "reports:read_published", "forecasts:read", "reports:read_drafts", "reports:write",
        "assistant:query", "surveys:import", "polls:import", "data:export", "issues:label",
    },
    "reviewer": {
        "data:read", "reports:read_published", "forecasts:read", "reports:read_drafts", "reports:review",
        "reports:publish", "issues:label", "assistant:query", "data:export",
    },
    "admin": {
        "data:read", "reports:read_published", "forecasts:read", "reports:read_drafts", "reports:write",
        "reports:review", "reports:publish", "assistant:query", "surveys:import", "polls:import",
        "data:export", "issues:label", "tenant:admin", "audit:read", "usage:read",
    },
}
# Platform operators run the shared data platform; they do not gain tenant research access.
OPERATOR_PERMISSIONS = {
    "sources:manage", "ingestion:run", "quarantine:review", "race_calls:record", "forecasts:run",
    "forecasts:publish", "ops:read", "tenants:manage",
}


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    label: str
    tenant_id: uuid.UUID
    tenant_slug: str
    role: str
    is_operator: bool
    permissions: frozenset[str]

    def has(self, perm: str) -> bool:
        return perm in self.permissions


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def decode_token(token: str) -> dict:
    s = get_settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed token") from exc
    alg = header.get("alg", "")
    if alg == "HS256":
        if s.environment not in ("development", "test") or not s.dev_auth_secret:
            AUTHZ_DENIALS.labels("dev_token_refused").inc()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token type not accepted")
        try:
            return jwt.decode(token, s.dev_auth_secret, algorithms=["HS256"], audience="election-dev",
                              options={"require": ["exp", "sub", "iss"]})
        except jwt.PyJWTError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
    if alg not in ("RS256", "RS384", "RS512", "ES256", "ES384", "PS256"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unsupported algorithm")
    if not (s.oidc_jwks_url and s.oidc_issuer and s.oidc_audience):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC is not configured")
    try:
        key = _jwks_client(s.oidc_jwks_url).get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=[alg], audience=s.oidc_audience, issuer=s.oidc_issuer,
                          options={"require": ["exp", "sub", "iss"]}, leeway=30)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc


def issue_dev_token(subject: str, email: str, ttl: int = 3600) -> str:
    """Development/test only. Raises outside those environments."""
    s = get_settings()
    if s.environment not in ("development", "test") or not s.dev_auth_secret:
        raise RuntimeError("dev tokens are disabled in this environment")
    now = int(time.time())
    return jwt.encode(
        {"sub": subject, "email": email, "email_verified": True, "iss": "election-dev", "aud": "election-dev",
         "iat": now, "exp": now + ttl},
        s.dev_auth_secret, algorithm="HS256",
    )


def get_db(request: Request):  # type: ignore[no-untyped-def]
    """Request-scoped session on the RLS-subject role. Tenant context is bound by `principal`."""
    from .db import app_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415

    session = sessionmaker(app_engine(), expire_on_commit=False)()
    try:
        session.begin()
        set_tenant(session, None)
        yield session
        if session.in_transaction():
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _resolve_user(db: Session, claims: dict) -> User:
    user = db.scalar(select(User).where(User.issuer == claims["iss"], User.subject == claims["sub"]))
    if user is None:
        user = User(issuer=claims["iss"], subject=claims["sub"], email=claims.get("email"),
                    display_name=claims.get("name") or claims.get("email"))
        db.add(user)
        db.flush()
    return user


def authenticate(request: Request, db: Session = Depends(get_db)) -> tuple[User, dict]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        AUTHZ_DENIALS.labels("missing_token").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    claims = decode_token(auth[7:].strip())
    return _resolve_user(db, claims), claims


def principal(
    request: Request,
    auth: tuple[User, dict] = Depends(authenticate),
    db: Session = Depends(get_db),
    x_tenant: str | None = Header(default=None),
) -> Principal:
    user, claims = auth
    if not x_tenant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant header is required")
    tenant = db.scalar(select(Tenant).where(Tenant.slug == x_tenant))
    membership = (
        db.get(Membership, {"tenant_id": tenant.id, "user_id": user.id}) if tenant is not None else None
    )
    if tenant is None or membership is None or tenant.status != "active":
        AUTHZ_DENIALS.labels("no_membership").inc()
        # Same response whether the tenant exists or not, to avoid tenant enumeration.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no access to this organization")
    sso = tenant.sso_config or {}
    if sso.get("required_issuer") and claims.get("iss") != sso["required_issuer"]:
        AUTHZ_DENIALS.labels("sso_issuer").inc()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this organization requires its SSO provider")
    perms = set(PERMISSIONS[membership.role])
    if user.is_platform_operator:
        perms |= OPERATOR_PERMISSIONS
    set_tenant(db, tenant.id)
    tenant_var.set(str(tenant.id))
    p = Principal(user.id, user.email or user.subject, tenant.id, tenant.slug, membership.role,
                  user.is_platform_operator, frozenset(perms))
    request.state.principal = p
    return p


def require(perm: str):  # type: ignore[no-untyped-def]
    def dep(p: Principal = Depends(principal)) -> Principal:
        if not p.has(perm):
            AUTHZ_DENIALS.labels(perm).inc()
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {perm}")
        return p

    return dep
