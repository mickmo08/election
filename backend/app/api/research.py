"""Tenant research workflows: assistant, reports, surveys, poll imports, exports, labels."""

from __future__ import annotations

import csv
import hashlib
import io
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit, entitlements, queue
from ..auth import Principal, get_db, require
from ..models import AssistantQuery, Document, Export, Report, SurveyDataset, Topic, TopicLabel
from ..services import reports as rep
from ..services import results, surveys
from ..services.assistant import engine
from ..storage import get_store
from .deps import assistant_rate_limited, rate_limited, read_upload

router = APIRouter(prefix="/api/v1", dependencies=[Depends(rate_limited)])


# ------------------------------------------------------------------ assistant

class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


@router.post("/assistant/query")
def ask(body: AskIn, request: Request, db: Session = Depends(get_db),
        p: Principal = Depends(assistant_rate_limited)) -> dict:
    entitlements.check_and_meter(db, p.tenant_id, "ai_queries")
    rec = engine.answer(db, tenant_id=p.tenant_id, user_id=p.user_id, question=body.question)
    audit.record_for(db, p, "assistant.query", target_type="assistant_query", target_id=str(rec.id),
                     details={"status": rec.status, "provider": rec.provider})
    return engine.to_view(rec)


@router.get("/assistant/history")
def history(db: Session = Depends(get_db), p: Principal = Depends(require("assistant:query"))) -> dict:
    rows = db.scalars(select(AssistantQuery).where(AssistantQuery.user_id == p.user_id)
                      .order_by(AssistantQuery.created_at.desc()).limit(50)).all()
    return {"queries": [engine.to_view(r) for r in rows]}


# ------------------------------------------------------------------ reports

class ReportIn(BaseModel):
    title: str = Field(min_length=3, max_length=500)


class VersionIn(BaseModel):
    body_markdown: str = Field(min_length=1, max_length=200_000)
    source_keys: list[str] = []
    methodology: str
    uncertainty: str
    ai_query_ids: list[str] = []
    countries: list[str] = []
    correction_note: str | None = None


class ReviewIn(BaseModel):
    approve: bool
    comment: str = Field(min_length=1, max_length=5000)


def _report(db: Session, report_id: uuid.UUID, p: Principal) -> Report:
    r = db.scalar(select(Report).where(Report.id == report_id).options(selectinload(Report.versions)))
    if r is None:  # RLS hides other tenants' reports entirely
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    if r.status != "published" and not p.has("reports:read_drafts"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return r


def _report_view(r: Report, p: Principal) -> dict:
    versions = [v for v in r.versions if p.has("reports:read_drafts") or v.published_at]
    return {"id": str(r.id), "title": r.title, "status": r.status, "published_version": r.published_version,
            "created_at": r.created_at, "versions": [
                {"version": v.version, "created_at": v.created_at, "ai_assisted": v.ai_assisted,
                 "contains_synthetic_data": v.contains_synthetic_data, "review_decision": v.review_decision,
                 "review_comment": v.review_comment, "published_at": v.published_at,
                 "correction_of_version": v.correction_of_version, "correction_note": v.correction_note,
                 "body_markdown": v.body_markdown, "sources": v.sources, "methodology": v.methodology,
                 "uncertainty": v.uncertainty, "data_freshness": v.data_freshness,
                 "reproducibility": v.reproducibility, "author_id": str(v.author_id)} for v in versions]}


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), p: Principal = Depends(require("reports:read_published"))) -> dict:
    q = select(Report).options(selectinload(Report.versions)).order_by(Report.created_at.desc())
    if not p.has("reports:read_drafts"):
        q = q.where(Report.status == "published")
    return {"reports": [{"id": str(r.id), "title": r.title, "status": r.status, "versions": len(r.versions),
                         "published_version": r.published_version, "created_at": r.created_at}
                        for r in db.scalars(q)]}


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, db: Session = Depends(get_db), p: Principal = Depends(require("reports:write"))) -> dict:
    r = rep.create(db, tenant_id=p.tenant_id, user_id=p.user_id, title=body.title)
    audit.record_for(db, p, "report.create", target_type="report", target_id=str(r.id))
    return {"id": str(r.id), "status": r.status}


@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, db: Session = Depends(get_db),
               p: Principal = Depends(require("reports:read_published"))) -> dict:
    return _report_view(_report(db, report_id, p), p)


@router.post("/reports/{report_id}/versions", status_code=201)
def add_version(report_id: uuid.UUID, body: VersionIn, db: Session = Depends(get_db),
                p: Principal = Depends(require("reports:write"))) -> dict:
    r = _report(db, report_id, p)
    v = rep.add_version(db, r, user_id=p.user_id, body=body.body_markdown, source_keys=body.source_keys,
                        methodology=body.methodology, uncertainty=body.uncertainty, ai_query_ids=body.ai_query_ids,
                        countries=body.countries, correction_note=body.correction_note)
    audit.record_for(db, p, "report.version", target_type="report", target_id=str(r.id), details={"version": v.version})
    return {"version": v.version, "status": r.status}


@router.post("/reports/{report_id}/submit")
def submit(report_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = Depends(require("reports:write"))) -> dict:
    r = _report(db, report_id, p)
    rep.submit(db, r)
    audit.record_for(db, p, "report.submit", target_type="report", target_id=str(r.id))
    return {"status": r.status}


@router.post("/reports/{report_id}/review")
def review(report_id: uuid.UUID, body: ReviewIn, db: Session = Depends(get_db),
           p: Principal = Depends(require("reports:review"))) -> dict:
    r = _report(db, report_id, p)
    rep.review(db, r, reviewer_id=p.user_id, approve=body.approve, comment=body.comment)
    audit.record_for(db, p, "report.review", target_type="report", target_id=str(r.id),
                     details={"approve": body.approve})
    return {"status": r.status}


@router.post("/reports/{report_id}/publish")
def publish(report_id: uuid.UUID, db: Session = Depends(get_db), p: Principal = Depends(require("reports:publish"))) -> dict:
    r = _report(db, report_id, p)
    try:
        v = rep.publish(db, r, publisher_id=p.user_id)
    except HTTPException as exc:
        audit.record_for(db, p, "report.publish", target_type="report", target_id=str(r.id), outcome="blocked",
                         details={"detail": exc.detail})
        db.commit()
        raise
    audit.record_for(db, p, "report.publish", target_type="report", target_id=str(r.id), details={"version": v.version})
    return {"status": r.status, "published_version": v.version}


@router.get("/reports/{report_id}/export")
def export_report(report_id: uuid.UUID, format: str = Query("md", pattern="^(md|html|json)$"),
                  version: int | None = None, db: Session = Depends(get_db),
                  p: Principal = Depends(require("reports:read_published"))) -> Response:
    r = _report(db, report_id, p)
    candidates = [v for v in r.versions if (version is None or v.version == version)
                  and (v.published_at or p.has("reports:read_drafts"))]
    if not candidates:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    content, mime = rep.render(r, candidates[-1], format)
    entitlements.check_and_meter(db, p.tenant_id, "exports", details={"report": str(r.id)})
    audit.record_for(db, p, "report.export", target_type="report", target_id=str(r.id),
                     details={"format": format, "version": candidates[-1].version})
    return Response(content, media_type=mime, headers={
        "content-disposition": f'attachment; filename="report-{r.id}-v{candidates[-1].version}.{format}"'})


# ------------------------------------------------------------------ dataset export

@router.get("/exports/contests.csv")
def export_contests(country: str, cycle: str, office: str | None = None, db: Session = Depends(get_db),
                    p: Principal = Depends(require("data:export"))) -> Response:
    rows = results.list_contests(db, country=country, cycle=cycle, office=office, limit=10000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# Source: election platform export; see /api/v1/sources for provenance and licences."])
    w.writerow(["contest_id", "name", "office", "admin_unit", "district", "status", "reporting_pct", "total_votes",
                "leader", "leader_share_pct", "runner_up", "runner_up_share_pct", "margin_pct", "retrieved_at"])
    for r in rows:
        t = r["top"] + [{}] * (2 - len(r["top"]))
        w.writerow([r["id"], r["name"], r["office"], r["admin_unit"], r["district"], r["status"], r["reporting_pct"],
                    r["total_votes"], t[0].get("label"), t[0].get("share"), t[1].get("label"), t[1].get("share"),
                    r["margin_pct"], r["retrieved_at"]])
    data = buf.getvalue()
    entitlements.check_and_meter(db, p.tenant_id, "exports", details={"dataset": "contests"})
    db.add(Export(tenant_id=p.tenant_id, user_id=p.user_id, dataset="contests",
                  params={"country": country, "cycle": cycle, "office": office}, row_count=len(rows),
                  sha256=hashlib.sha256(data.encode()).hexdigest()))
    audit.record_for(db, p, "export.dataset", target_type="dataset", target_id="contests",
                     details={"country": country, "cycle": cycle, "rows": len(rows)})
    return Response(data, media_type="text/csv",
                    headers={"content-disposition": f'attachment; filename="contests-{country}-{cycle}.csv"'})


# ------------------------------------------------------------------ surveys

@router.post("/surveys", status_code=201)
async def import_survey(request: Request, file: UploadFile = File(...), name: str = Form(...),
                        consent_basis: str = Form(...), deidentification_attestation: str = Form(...),
                        sampling_method: str = Form(..., pattern="^(probability|nonprobability|mixed|unknown)$"),
                        population: str = Form(..., pattern="^(a|rv|lv|v)$"), weight_column: str | None = Form(None),
                        db: Session = Depends(get_db), p: Principal = Depends(require("surveys:import"))) -> dict:
    data = await read_upload(request, file)
    entitlements.check_and_meter(db, p.tenant_id, "imports", details={"kind": "survey"})
    entitlements.check_and_meter(db, p.tenant_id, "storage_bytes", len(data))
    ds = surveys.import_survey(db, tenant_id=p.tenant_id, user_id=p.user_id, name=name, content=data,
                               consent_basis=consent_basis, deidentification_attestation=deidentification_attestation,
                               sampling_method=sampling_method, population=population, weight_column=weight_column)
    audit.record_for(db, p, "survey.import", target_type="survey_dataset", target_id=str(ds.id),
                     details={"rows": ds.n_rows, "sha256": ds.raw_sha256})
    return {"id": str(ds.id), "rows": ds.n_rows, "columns": ds.columns}


@router.get("/surveys")
def list_surveys(db: Session = Depends(get_db), p: Principal = Depends(require("data:read"))) -> dict:
    return {"datasets": [{"id": str(d.id), "name": d.name, "n_rows_band": surveys._band(d.n_rows),
                          "columns": d.columns, "sampling_method": d.sampling_method, "population": d.population,
                          "created_at": d.created_at} for d in db.scalars(select(SurveyDataset))]}


@router.get("/surveys/{dataset_id}/crosstab")
def crosstab(dataset_id: uuid.UUID, row: str, col: str | None = None, db: Session = Depends(get_db),
             p: Principal = Depends(require("data:read"))) -> dict:
    out = surveys.crosstab(db, dataset_id, row, col)
    audit.record_for(db, p, "survey.aggregate", target_type="survey_dataset", target_id=str(dataset_id),
                     details={"row": row, "col": col})
    return out


# ------------------------------------------------------------------ tenant poll import (private polls)

@router.post("/polls/import", status_code=202)
async def import_polls(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                       p: Principal = Depends(require("polls:import"))) -> dict:
    data = await read_upload(request, file)
    entitlements.check_and_meter(db, p.tenant_id, "imports", details={"kind": "polls"})
    key, digest = get_store().put(data, source_key=f"tenant-uploads/{p.tenant_id}")
    job = queue.enqueue(db, "ingest_upload", {"source_key": "us-polls-editorial", "storage_key": key,
                                              "filename": file.filename, "params": {"tenant_id": str(p.tenant_id)},
                                              "by": p.label}, idempotency_key=f"poll-upload:{p.tenant_id}:{digest}",
                        tenant_id=p.tenant_id)
    audit.record_for(db, p, "polls.import", target_type="job", target_id=str(job), details={"sha256": digest})
    return {"job_id": str(job), "sha256": digest}


# ------------------------------------------------------------------ issue labelling (human review)

class LabelIn(BaseModel):
    document_id: uuid.UUID
    topic_key: str
    is_relevant: bool
    split: str = Field("eval", pattern="^(eval|dev)$")


@router.get("/issues/review-queue")
def review_queue(country: str, limit: int = Query(20, le=100), db: Session = Depends(get_db),
                 p: Principal = Depends(require("issues:label"))) -> dict:
    labelled = select(TopicLabel.document_id).where(TopicLabel.reviewer == p.label)
    docs = db.scalars(select(Document).where(Document.country_code == country, Document.duplicate_of_id.is_(None),
                                             Document.id.not_in(labelled)).order_by(Document.published_at.desc())
                      .limit(limit)).all()
    from ..services.issues import classify  # noqa: PLC0415

    return {"documents": [{"id": str(d.id), "title": d.title, "body": d.body[:1500], "language": d.language,
                           "published_at": d.published_at, "predicted": classify(f"{d.title}. {d.body}")}
                          for d in docs],
            "topics": [t.key for t in db.scalars(select(Topic))]}


@router.post("/issues/labels", status_code=201)
def add_label(body: LabelIn, db: Session = Depends(get_db), p: Principal = Depends(require("issues:label"))) -> dict:
    topic = db.scalar(select(Topic).where(Topic.key == body.topic_key))
    if topic is None or db.get(Document, body.document_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document or topic not found")
    db.add(TopicLabel(document_id=body.document_id, topic_id=topic.id, is_relevant=body.is_relevant,
                      reviewer=p.label, split=body.split))
    audit.record_for(db, p, "issues.label", target_type="document", target_id=str(body.document_id))
    return {"ok": True}
