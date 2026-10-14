"""Editorial workflow: drafts, separation of duties, publication rules, corrections, exports."""

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import tenant_session


def _version(client, h, rid, **kw):
    body = {
        "body_markdown": "Findings: turnout rose.",
        "methodology": "Certified returns compared across cycles.",
        "uncertainty": "Certified totals; no sampling error.",
        "source_keys": ["editorial-desk"],
        **kw,
    }
    return client.post(f"/api/v1/reports/{rid}/versions", headers=h, json=body)


def test_full_workflow_with_correction(client, headers, tenants):
    analyst, reviewer, admin, viewer = (
        headers(s) for s in ("demo-analyst", "demo-reviewer", "demo-admin", "demo-viewer")
    )
    q = client.post(
        "/api/v1/assistant/query", headers=analyst, json={"question": "Which data sources are unavailable?"}
    )
    rid = client.post("/api/v1/reports", headers=analyst, json={"title": "Source availability brief"}).json()["id"]
    assert _version(client, analyst, rid, methodology="").status_code == 422
    assert _version(client, analyst, rid, ai_query_ids=[q.json()["id"]]).status_code == 201
    assert client.post(f"/api/v1/reports/{rid}/publish", headers=admin).status_code == 409  # not approved
    assert client.post(f"/api/v1/reports/{rid}/submit", headers=analyst).status_code == 200
    assert client.get(f"/api/v1/reports/{rid}", headers=viewer).status_code == 404  # drafts hidden from viewers
    assert (
        client.post(
            f"/api/v1/reports/{rid}/review",
            headers=reviewer,
            json={"approve": True, "comment": "Checked against sources"},
        ).status_code
        == 200
    )
    r = client.post(f"/api/v1/reports/{rid}/publish", headers=reviewer)
    assert r.status_code == 200 and r.json()["published_version"] == 1
    md = client.get(f"/api/v1/reports/{rid}/export?format=md", headers=viewer)
    assert md.status_code == 200 and "AI-assisted" in md.text and "Reproducibility" in md.text
    assert "Content SHA-256" in md.text
    # published versions are immutable in the database
    t, _ = tenants
    try:
        with tenant_session(t["demo-newsroom"]) as db:
            db.execute(text("UPDATE report_versions SET body_markdown='x' WHERE report_id=:r"), {"r": rid})
        raise AssertionError("published version was modified")
    except DBAPIError:
        pass
    # corrections need a note, a new version and a fresh review
    assert _version(client, analyst, rid).status_code == 422
    assert _version(client, analyst, rid, correction_note="Corrected a source attribution.").status_code == 201
    client.post(f"/api/v1/reports/{rid}/submit", headers=analyst)
    client.post(f"/api/v1/reports/{rid}/review", headers=reviewer, json={"approve": True, "comment": "ok"})
    assert client.post(f"/api/v1/reports/{rid}/publish", headers=reviewer).json()["published_version"] == 2
    rep = client.get(f"/api/v1/reports/{rid}", headers=viewer).json()
    assert [v["version"] for v in rep["versions"]] == [1, 2] and rep["versions"][1]["correction_of_version"] == 1
    actions = [e["action"] for e in client.get("/api/v1/admin/audit?limit=50", headers=admin).json()["events"]]
    assert "report.publish" in actions and "report.export" in actions


def test_author_cannot_self_review(client, headers):
    from .conftest import make_user

    make_user("demo-analyst", "demo-newsroom", "analyst")
    admin = headers("demo-admin")
    rid = client.post("/api/v1/reports", headers=admin, json={"title": "Self review attempt"}).json()["id"]
    _version(client, admin, rid)
    client.post(f"/api/v1/reports/{rid}/submit", headers=admin)
    r = client.post(f"/api/v1/reports/{rid}/review", headers=admin, json={"approve": True, "comment": "me"})
    assert r.status_code == 403


def test_synthetic_and_blackout_block_publication(client, headers):
    analyst, reviewer = headers("demo-analyst"), headers("demo-reviewer")
    rid = client.post("/api/v1/reports", headers=analyst, json={"title": "Synthetic polls note"}).json()["id"]
    _version(client, analyst, rid, source_keys=["xs-synthetic"], countries=["XS"])
    client.post(f"/api/v1/reports/{rid}/submit", headers=analyst)
    client.post(f"/api/v1/reports/{rid}/review", headers=reviewer, json={"approve": True, "comment": "ok"})
    r = client.post(f"/api/v1/reports/{rid}/publish", headers=reviewer)
    assert r.status_code == 409
    assert any("SYNTHETIC" in b for b in r.json()["detail"]["blockers"])


def test_contest_export_metered_and_audited(client, headers):
    r = client.get(
        "/api/v1/exports/contests.csv?country=XS&cycle=2024&office=xs_assembly", headers=headers("demo-analyst")
    )
    assert r.status_code == 200 and r.text.count("\n") >= 41 and "attachment" in r.headers["content-disposition"]
    usage = client.get("/api/v1/admin/usage", headers=headers("demo-admin")).json()
    assert usage["metrics"]["exports"]["used"] >= 1
