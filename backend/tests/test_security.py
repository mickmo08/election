"""Authentication, authorization (RBAC), cross-tenant isolation (API and database), immutability."""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db import tenant_session
from app.models import AssistantQuery, Report, SurveyResponse

from .conftest import make_user

SURVEY = b"q_vote,age_band,wt\n" + b"".join(
    f"{'A' if i % 3 else 'B'},{'18-34' if i % 2 else '35+'},1.0\n".encode() for i in range(120)
)


def test_unauthenticated_and_tenant_header(client, headers):
    assert client.get("/api/v1/countries").status_code == 401
    h = headers("demo-analyst")
    assert client.get("/api/v1/countries", headers={"authorization": h["authorization"]}).status_code == 400
    # unknown tenant and non-member tenant are indistinguishable
    r1 = client.get("/api/v1/countries", headers={**h, "x-tenant": "no-such-tenant"})
    r2 = client.get("/api/v1/countries", headers={**h, "x-tenant": "demo-university"})
    assert r1.status_code == r2.status_code == 403 and r1.json() == r2.json()


def test_forged_and_expired_tokens_rejected(client):
    forged = jwt.encode(
        {"sub": "demo-admin", "iss": "election-dev", "aud": "election-dev", "exp": int(time.time()) + 60},
        "wrong-secret-wrong-secret-wrong-secret!",
        algorithm="HS256",
    )
    expired = jwt.encode(
        {"sub": "demo-admin", "iss": "election-dev", "aud": "election-dev", "exp": int(time.time()) - 60},
        "test-secret-0123456789abcdef0123456789abcdef",
        algorithm="HS256",
    )
    none_alg = jwt.encode({"sub": "demo-admin", "iss": "x", "exp": int(time.time()) + 60}, None, algorithm="none")
    for tok in (forged, expired, none_alg, "garbage"):
        r = client.get("/api/v1/me", headers={"authorization": f"Bearer {tok}", "x-tenant": "demo-newsroom"})
        assert r.status_code == 401, tok


def test_oidc_rs256_validation(monkeypatch):
    from app import auth
    from app.config import get_settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    s = get_settings()
    monkeypatch.setattr(s, "oidc_issuer", "https://idp.test")
    monkeypatch.setattr(s, "oidc_audience", "election-api")
    monkeypatch.setattr(s, "oidc_jwks_url", "https://idp.test/jwks")

    class FakeJWKS:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr(auth, "_jwks_client", lambda url: FakeJWKS())
    good = jwt.encode(
        {"sub": "u1", "iss": "https://idp.test", "aud": "election-api", "exp": int(time.time()) + 60},
        key,
        algorithm="RS256",
        headers={"kid": "k1"},
    )
    assert auth.decode_token(good)["sub"] == "u1"
    bad_aud = jwt.encode(
        {"sub": "u1", "iss": "https://idp.test", "aud": "other", "exp": int(time.time()) + 60}, key, algorithm="RS256"
    )
    with pytest.raises(Exception) as exc:
        auth.decode_token(bad_aud)
    assert getattr(exc.value, "status_code", None) == 401


def test_production_config_guards():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(environment="production", dev_auth_secret="x", oidc_issuer="i", oidc_audience="a", oidc_jwks_url="j")
    with pytest.raises(ValidationError):
        Settings(environment="production", dev_auth_secret=None)
    oidc = {"oidc_issuer": "i", "oidc_audience": "a", "oidc_jwks_url": "j"}
    with pytest.raises(ValidationError):  # development database credentials are rejected
        Settings(environment="production", dev_auth_secret=None, **oidc)
    prod_urls = {
        k: f"postgresql+psycopg://{r}:from-secret-manager@db.internal/election"
        for k, r in (
            ("database_url", "svc_app"),
            ("worker_database_url", "svc_worker"),
            ("migration_database_url", "svc_owner"),
        )
    }
    ok = Settings(environment="production", dev_auth_secret=None, **oidc, **prod_urls)
    assert not ok.allows_synthetic_data


def test_dev_token_refused_outside_dev(monkeypatch, client, headers):
    from app.config import get_settings

    h = headers("demo-analyst")
    monkeypatch.setattr(get_settings(), "environment", "production")
    assert client.get("/api/v1/me", headers=h).status_code == 401
    assert client.post("/api/v1/dev/token", json={"subject": "demo-analyst"}).status_code == 404


@pytest.mark.parametrize(
    "subject,method,path,expected",
    [
        ("demo-viewer", "post", "/api/v1/reports", 403),
        ("demo-viewer", "post", "/api/v1/assistant/query", 403),
        ("demo-viewer", "get", "/api/v1/exports/contests.csv?country=XS&cycle=2024", 403),
        ("demo-analyst", "get", "/api/v1/admin/audit", 403),
        ("demo-analyst", "get", "/api/v1/admin/members", 403),
        ("demo-reviewer", "post", "/api/v1/admin/forecasts", 403),
        ("demo-analyst", "get", "/api/v1/admin/quarantine", 403),
        ("demo-analyst", "post", "/api/v1/admin/sources/editorial-desk/ingest", 403),
    ],
)
def test_role_matrix(client, headers, subject, method, path, expected):
    kw = (
        {"json": {"title": "x", "question": "test q", "country": "XS", "office": "x", "cycle": 1}}
        if method == "post"
        else {}
    )
    r = getattr(client, method)(path, headers=headers(subject), **kw)
    assert r.status_code == expected, r.text


def test_tenant_admin_is_not_platform_operator(client, headers):
    make_user("uni-admin", "demo-university", "admin")
    h = headers("uni-admin", "demo-university")
    assert client.get("/api/v1/admin/members", headers=h).status_code == 200
    assert client.get("/api/v1/admin/ops/status", headers=h).status_code == 403
    assert (
        client.post(
            "/api/v1/admin/sources/editorial-desk/status", headers=h, json={"status": "disabled", "reason": "nope"}
        ).status_code
        == 403
    )


def test_cross_tenant_isolation_api(client, headers):
    a = headers("demo-analyst")  # demo-newsroom
    b = headers("uni-analyst", "demo-university")
    rid = client.post("/api/v1/reports", headers=a, json={"title": "Newsroom private draft"}).json()["id"]
    assert client.get(f"/api/v1/reports/{rid}", headers=b).status_code == 404
    assert rid not in [r["id"] for r in client.get("/api/v1/reports", headers=b).json()["reports"]]
    assert client.post(
        f"/api/v1/reports/{rid}/versions",
        headers=b,
        json={"body_markdown": "x", "methodology": "m", "uncertainty": "u"},
    ).status_code in (403, 404)
    sid = client.post(
        "/api/v1/surveys",
        headers=a,
        files={"file": ("s.csv", SURVEY, "text/csv")},
        data={
            "name": "Panel wave 1",
            "consent_basis": "Opt-in panel consent recorded by vendor, 2026",
            "deidentification_attestation": "Direct identifiers removed by vendor before delivery",
            "sampling_method": "probability",
            "population": "a",
            "weight_column": "wt",
        },
    ).json()["id"]
    assert client.get(f"/api/v1/surveys/{sid}/crosstab?row=q_vote", headers=b).status_code == 404
    assert sid not in [d["id"] for d in client.get("/api/v1/surveys", headers=b).json()["datasets"]]
    q = client.post("/api/v1/assistant/query", headers=a, json={"question": "Which data sources are unavailable?"})
    assert q.status_code == 200
    assert q.json()["id"] not in [x["id"] for x in client.get("/api/v1/assistant/history", headers=b).json()["queries"]]
    # audit log is tenant scoped
    actions_b = {
        e["target_id"]
        for e in client.get("/api/v1/admin/audit", headers=headers("uni-admin", "demo-university")).json()["events"]
    }
    assert rid not in actions_b


def test_rls_enforced_in_database_without_app_filters(tenants):
    t, _ = tenants
    a, b = t["demo-newsroom"], t["demo-university"]
    with tenant_session(a) as db:
        assert db.scalar(text("SELECT count(*) FROM reports")) >= 1
        assert db.scalar(text("SELECT count(*) FROM survey_responses")) >= 1
    with tenant_session(b) as db:  # raw SQL, no WHERE clause: RLS alone hides tenant A rows
        assert db.scalar(text("SELECT count(*) FROM reports WHERE tenant_id = :a"), {"a": a}) == 0
        assert db.scalar(text("SELECT count(*) FROM survey_responses")) == 0
        assert db.scalar(select(AssistantQuery).where(AssistantQuery.tenant_id == a)) is None
    with tenant_session(None) as db:  # no tenant bound -> nothing tenant-owned visible
        assert db.scalar(text("SELECT count(*) FROM reports")) == 0
        assert db.scalar(text("SELECT count(*) FROM polls WHERE tenant_id IS NOT NULL")) == 0
        assert db.scalar(text("SELECT count(*) FROM polls")) > 0  # shared platform polls remain visible
    with pytest.raises(DBAPIError), tenant_session(b) as db:  # cannot write into another tenant
        db.add(Report(tenant_id=a, title="smuggled", created_by=uuid.uuid4()))
        db.flush()
    with pytest.raises((DBAPIError, ProgrammingError)), tenant_session(b) as db:
        db.execute(text("UPDATE survey_responses SET weight = 99"))  # affects 0 rows under RLS...
        db.execute(text("SET LOCAL row_security = off"))  # ...and RLS cannot be switched off by the app role
        db.execute(text("SELECT count(*) FROM survey_responses")).scalar()


def test_app_role_cannot_tamper_with_history(tenants):
    t, _ = tenants
    with pytest.raises(DBAPIError), tenant_session(t["demo-newsroom"]) as db:
        db.execute(text("UPDATE audit_events SET action = 'x'"))
    with pytest.raises(DBAPIError), tenant_session(t["demo-newsroom"]) as db:
        db.execute(text("DELETE FROM result_snapshots"))


def test_survey_rows_never_exposed(client, headers):
    a = headers("demo-analyst")
    paths = list(client.app.openapi()["paths"])
    assert any("surveys" in p for p in paths)
    assert not any("responses" in p for p in paths)
    sid = client.get("/api/v1/surveys", headers=a).json()["datasets"][0]["id"]
    body = client.get(f"/api/v1/surveys/{sid}/crosstab?row=q_vote&col=age_band", headers=a).json()
    assert "answers" not in str(body) and 'weight"' not in str(body)
    with tenant_session(None) as db:
        assert db.scalar(select(SurveyResponse)) is None


def test_upload_protections(client, headers):
    a = headers("demo-analyst")
    r = client.post("/api/v1/polls/import", headers=a, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415
    r = client.post("/api/v1/polls/import", headers=a, files={"file": ("x.zip", b"not zip", "application/zip")})
    assert r.status_code == 415
    r = client.post(
        "/api/v1/surveys",
        headers=a,
        files={"file": ("s.csv", b"email,q\nx@y.com,1\n", "text/csv")},
        data={
            "name": "n",
            "consent_basis": "c" * 30,
            "deidentification_attestation": "d" * 30,
            "sampling_method": "probability",
            "population": "a",
        },
    )
    assert r.status_code == 422 and "identifier" in r.text
    r = client.post(
        "/api/v1/surveys",
        headers=a,
        files={"file": ("s.csv", b"contact,q\nx@y.com,1\n", "text/csv")},
        data={
            "name": "n",
            "consent_basis": "c" * 30,
            "deidentification_attestation": "d" * 30,
            "sampling_method": "probability",
            "population": "a",
        },
    )
    assert r.status_code == 422 and "email" in r.text


def test_rate_limit(monkeypatch, client, headers):
    from app.api import deps
    from app.ratelimit import TokenBucket

    monkeypatch.setattr(deps, "_general", TokenBucket(2, burst=2))
    codes = [client.get("/healthz").status_code] + [
        client.get("/api/v1/countries", headers=headers("demo-viewer")).status_code for _ in range(4)
    ]
    assert 429 in codes
    r = [client.get("/api/v1/countries", headers=headers("demo-viewer")) for _ in range(2)][-1]
    assert r.status_code == 429 and "retry-after" in r.headers


def test_security_headers(client):
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers
