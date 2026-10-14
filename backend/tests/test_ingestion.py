import io
import json
import zipfile
from pathlib import Path

import pytest
import shapefile
from sqlalchemy import func, select

from app.ingestion import adapters  # noqa: F401
from app.ingestion.framework import FetchedFile, SourceUnavailable, run_ingestion
from app.models import (
    Candidacy,
    Contest,
    District,
    DistrictPlan,
    Document,
    QuarantineItem,
    RawFile,
    ResultSnapshot,
    Source,
)

FIX = Path(__file__).parent / "fixtures"


def ff(name: str, content: bytes) -> FetchedFile:
    return FetchedFile(url=f"test://{name}", content=content, content_type="text/csv", filename=name)


def activate(db, key: str, **kw) -> Source:
    s = db.scalar(select(Source).where(Source.key == key))
    s.status = "active"
    for k, v in kw.items():
        setattr(s, k, v)
    db.commit()
    return s


def test_unavailable_source_is_recorded_not_faked(wdb):
    with pytest.raises(SourceUnavailable) as exc:
        run_ingestion(wdb, "us-fec-openfec", {"election_year": 2026})
    assert "api.data.gov" in str(exc.value) or "pending_credentials" in str(exc.value)


def test_medsl_load_validate_quarantine_and_idempotency(wdb):
    data = (FIX / "medsl_house_sample.csv").read_bytes()
    run = run_ingestion(wdb, "us-medsl-house", {}, [ff("house.csv", data)])
    assert run.status == "partial"  # NY-02 totals error quarantined, others loaded
    items = wdb.scalars(select(QuarantineItem).where(QuarantineItem.run_id == run.id)).all()
    rules = {i.rule for i in items}
    assert {"totals", "special_election_date", "party_unresolved"} <= rules
    assert any(i.rule == "totals" and i.severity == "error" for i in items)
    wy = wdb.scalar(select(Contest).where(Contest.name == "U.S. House WY-AL (2022)"))
    snap = wdb.scalar(select(ResultSnapshot).where(ResultSnapshot.contest_id == wy.id))
    assert snap.status == "certified" and snap.total_votes == 1600 and snap.ingestion_run_id == run.id
    # fusion: one candidacy for GAMMA with combined votes
    ny1 = wdb.scalar(select(Contest).where(Contest.name == "U.S. House NY-01 (2022)"))
    s1 = wdb.scalar(select(ResultSnapshot).where(ResultSnapshot.contest_id == ny1.id))
    gamma = next(ln for ln in s1.lines if ln.label == "TESTPERSON GAMMA")
    assert gamma.votes == 800
    assert wdb.scalar(select(Contest).where(Contest.name == "U.S. House NY-02 (2022)")) is not None
    ny2 = wdb.scalar(select(Contest).where(Contest.name == "U.S. House NY-02 (2022)"))
    assert wdb.scalar(select(func.count()).select_from(ResultSnapshot).where(ResultSnapshot.contest_id == ny2.id)) == 0
    # provenance
    raw = wdb.get(RawFile, run.raw_file_ids[0])
    assert raw.sha256 and raw.schema_version == "medsl-constituency-returns-v1" and raw.publisher.startswith("MIT")
    # idempotent re-run returns the same run and writes nothing new
    n_before = wdb.scalar(select(func.count()).select_from(ResultSnapshot))
    again = run_ingestion(wdb, "us-medsl-house", {}, [ff("house.csv", data)])
    assert again.id == run.id
    assert wdb.scalar(select(func.count()).select_from(ResultSnapshot)) == n_before


def test_structural_failure_loads_nothing(wdb):
    bad = b"year,state_po,office\n2022,WY,US HOUSE\n"
    n_before = wdb.scalar(select(func.count()).select_from(Contest))
    run = run_ingestion(wdb, "us-medsl-house", {}, [ff("bad.csv", bad)])
    assert run.status == "quarantined"
    item = wdb.scalar(select(QuarantineItem).where(QuarantineItem.run_id == run.id))
    assert item.rule == "schema" and "candidatevotes" in item.message
    assert wdb.scalar(select(func.count()).select_from(Contest)) == n_before


def _results_csv(
    status: str, votes_a: int, votes_b: int, pct: str = "", as_of="2026-11-04T03:00:00+00:00", note: str = ""
) -> bytes:
    hdr = (
        "country,election_kind,election_date,admin_unit,office_key,district,candidate,party,votes,status,"
        "source_as_of,reporting_pct,correction_note\n"
    )
    rows = (
        f"US,general,2026-11-03,WY,us_house,WY-AL,Testperson One,REP,{votes_a},{status},{as_of},{pct},{note}\n"
        f"US,general,2026-11-03,WY,us_house,WY-AL,Testperson Two,DEM,{votes_b},{status},{as_of},{pct},{note}\n"
    )
    return (hdr + rows).encode()


def test_official_results_status_lifecycle(wdb):
    activate(wdb, "us-state-official-results")
    r1 = run_ingestion(
        wdb, "us-state-official-results", {}, [ff("r1.csv", _results_csv("Election Night", 100, 80, "40"))]
    )
    assert r1.status == "succeeded"
    contest = wdb.scalar(select(Contest).where(Contest.name.like("U.S. Representative WY-AL (2026%")))
    snaps = lambda: wdb.scalars(
        select(ResultSnapshot)
        .where(ResultSnapshot.contest_id == contest.id)  # noqa: E731
        .order_by(ResultSnapshot.retrieved_at)
    ).all()
    assert snaps()[-1].status == "preliminary" and snaps()[-1].reporting_pct == 40
    run_ingestion(wdb, "us-state-official-results", {}, [ff("r2.csv", _results_csv("Unofficial", 300, 250, ""))])
    assert snaps()[-1].status == "unofficial" and snaps()[-1].reporting_pct is None  # unsupported -> not shown
    run_ingestion(wdb, "us-state-official-results", {}, [ff("r3.csv", _results_csv("Certified", 310, 255, ""))])
    assert snaps()[-1].status == "certified"
    # certified totals change without a correction label -> quarantined, not applied
    r4 = run_ingestion(wdb, "us-state-official-results", {}, [ff("r4.csv", _results_csv("Certified", 320, 255, ""))])
    assert any(
        i.rule == "certified_changed" for i in wdb.scalars(select(QuarantineItem).where(QuarantineItem.run_id == r4.id))
    )
    assert snaps()[-1].total_votes == 565
    # amended canvass accepted and linked to what it supersedes
    run_ingestion(
        wdb,
        "us-state-official-results",
        {},
        [ff("r5.csv", _results_csv("Amended", 320, 255, "", note="Precinct 4 transposition"))],
    )
    last = snaps()[-1]
    assert last.status == "corrected" and last.supersedes_id == snaps()[-2].id
    assert last.correction_note == "Precinct 4 transposition"
    assert len(snaps()) == 4


def test_unknown_status_label_quarantined(wdb):
    activate(wdb, "us-state-official-results")
    run = run_ingestion(wdb, "us-state-official-results", {}, [ff("x.csv", _results_csv("Vibes", 1, 1))])
    assert any(i.rule == "status" for i in wdb.scalars(select(QuarantineItem).where(QuarantineItem.run_id == run.id)))


def test_fec_page_processing_and_secret_redaction(wdb, monkeypatch):
    import httpx

    from app.ingestion.adapters import fec

    page = {
        "pagination": {"page": 1, "pages": 1, "count": 4, "per_page": 100},
        "results": [
            {
                "candidate_id": "H6WY00999",
                "name": "TESTPERSON, ONE",
                "party": "REP",
                "office": "H",
                "state": "WY",
                "district": "00",
                "election_years": [2026],
                "incumbent_challenge": "I",
            },
            {
                "candidate_id": "BAD",
                "name": "X",
                "party": "DEM",
                "office": "H",
                "state": "WY",
                "district": "00",
                "election_years": [2026],
            },
            {
                "candidate_id": "H6WY00998",
                "name": "TESTPERSON, TWO",
                "party": "DEM",
                "office": "H",
                "state": "WY",
                "district": "07",
                "election_years": [2026],
            },
            {
                "candidate_id": "S6FL00999",
                "name": "TESTPERSON, THREE",
                "party": "DEM",
                "office": "S",
                "state": "FL",
                "district": "00",
                "election_years": [2026],
            },
        ],
    }

    def handler(request):
        assert request.url.params["api_key"] == "SECRET-KEY-123"
        return httpx.Response(200, json=page)

    real_client = httpx.Client
    monkeypatch.setattr(fec.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(fec.time, "sleep", lambda s: None)
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "fec_api_key", "SECRET-KEY-123")
    activate(wdb, "us-fec-openfec")
    run = run_ingestion(wdb, "us-fec-openfec", {"election_year": 2026, "office": "H"})
    rules = [i.rule for i in wdb.scalars(select(QuarantineItem).where(QuarantineItem.run_id == run.id))]
    assert "identifier" in rules and "district_range" in rules and "senate_special_unconfirmed" in rules
    raw = wdb.get(RawFile, run.raw_file_ids[0])
    assert "SECRET-KEY-123" not in raw.url and "REDACTED" in raw.url
    from app.storage import get_store

    assert b"SECRET-KEY-123" not in get_store().get(raw.storage_key)
    cy = wdb.scalar(select(Candidacy).where(Candidacy.ballot_name == "TESTPERSON, ONE"))
    assert cy.status == "filed_with_fec" and cy.incumbent is True
    for k in ("us-fec-openfec", "us-state-official-results"):
        wdb.scalar(select(Source).where(Source.key == k)).status = "pending_credentials"
    wdb.commit()


def test_documents_licence_and_personal_data_controls(wdb):
    s = activate(wdb, "us-licensed-news", permits_text_analysis=False)
    line = json.dumps(
        {
            "external_id": "t1",
            "kind": "news",
            "title": "Test",
            "body": "Inflation and prices rose.",
            "published_at": "2026-10-01T00:00:00+00:00",
            "country": "US",
        }
    )
    run = run_ingestion(wdb, "us-licensed-news", {}, [ff("d.jsonl", line.encode())])
    assert run.status == "quarantined"
    s.permits_text_analysis = True
    wdb.commit()
    lines = [
        line,
        json.dumps(
            {
                "external_id": "t2",
                "kind": "public_discussion",
                "title": "x",
                "body": "y",
                "published_at": "2026-10-01T00:00:00+00:00",
                "country": "US",
                "author": "someone",
            }
        ),
        json.dumps(
            {
                "external_id": "t3",
                "kind": "news",
                "title": "Test (syndicated)",
                "body": "Inflation and prices rose.",
                "published_at": "2026-10-01T05:00:00+00:00",
                "country": "US",
            }
        ),
    ]
    run = run_ingestion(wdb, "us-licensed-news", {}, [ff("d2.jsonl", "\n".join(lines).encode())])
    rules = [i.rule for i in wdb.scalars(select(QuarantineItem).where(QuarantineItem.run_id == run.id))]
    assert "personal_data" in rules
    t3 = wdb.scalar(select(Document).where(Document.external_id == "t3"))
    t1 = wdb.scalar(select(Document).where(Document.external_id == "t1"))
    assert t3.duplicate_of_id == t1.id
    s.status, s.permits_text_analysis = "pending_license", False
    wdb.commit()


def _shapefile_zip(records: list[tuple[str, str]]) -> bytes:
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    w.field("STATEFP", "C", 2)
    w.field("CD119FP", "C", 2)
    for i, (st, cd) in enumerate(records):
        w.poly([[[i, 0], [i, 1], [i + 1, 1], [i + 1, 0], [i, 0]]])
        w.record(st, cd)
    w.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("t.shp", shp.getvalue())
        z.writestr("t.shx", shx.getvalue())
        z.writestr("t.dbf", dbf.getvalue())
    return buf.getvalue()


def test_census_boundaries_and_apportionment_check(wdb):
    activate(wdb, "us-census-cd-boundaries")
    data = _shapefile_zip([("56", "00"), ("10", "00"), ("44", "01"), ("44", "02"), ("33", "01")])
    run = run_ingestion(
        wdb,
        "us-census-cd-boundaries",
        {"congress": 119, "valid_from": "2025-01-03"},
        [FetchedFile("test://cd.zip", data, "application/zip", filename="cd.zip")],
    )
    plan = wdb.scalar(select(DistrictPlan).where(DistrictPlan.name == "119th Congress districts: Wyoming"))
    assert plan.boundary_status == "geometry_loaded"
    d = wdb.scalar(select(District).where(District.plan_id == plan.id))
    assert d.code == "WY-AL" and d.geometry["type"] == "Polygon"
    msgs = [i.message for i in wdb.scalars(select(QuarantineItem).where(QuarantineItem.run_id == run.id))]
    assert any("state 33: 1 districts in file, 2 apportioned" in m for m in msgs)  # NH has 2 seats
    bomb = run_ingestion(
        wdb,
        "us-census-cd-boundaries",
        {"congress": 119, "valid_from": "2025-01-03"},
        [FetchedFile("test://x.zip", b"not a zip", "application/zip", filename="x.zip")],
    )
    assert bomb.status == "quarantined"
    wdb.scalar(select(Source).where(Source.key == "us-census-cd-boundaries")).status = "network_blocked"
    wdb.commit()


def test_editorial_calendar_requires_citation(wdb):
    csv = (
        "country,election_kind,election_date,admin_unit,office_key,district,citation_url,verified_by,contest_name\n"
        "US,general,2026-11-03,WY,governor,,,editor@test,Governor of Wyoming\n"
        "US,general,2026-11-03,WY,governor,,https://example.gov/calendar,editor@test,Governor of Wyoming\n"
    )
    run = run_ingestion(wdb, "editorial-desk", {}, [ff("cal.csv", csv.encode())])
    rules = [i.rule for i in wdb.scalars(select(QuarantineItem).where(QuarantineItem.run_id == run.id))]
    assert rules == ["citation_required"]
    assert run.stats.get("contests_upserted") == 1


def test_raw_files_are_immutable(wdb):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    rid = wdb.scalar(select(RawFile.id).limit(1))
    with pytest.raises(DBAPIError):
        wdb.execute(text("UPDATE raw_files SET url='tampered' WHERE id=:i"), {"i": rid})
    wdb.rollback()
