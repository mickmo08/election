"""Research reports: drafts, review (separation of duties), versioned publication and corrections."""

from __future__ import annotations

import hashlib
import html
import os
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AssistantQuery,
    Country,
    Election,
    ElectionCycle,
    ModelVersion,
    Report,
    ReportVersion,
    Source,
    Tenant,
)
from .freshness import source_freshness


def _app_version() -> str:
    """Build identifier injected at image build time (Dockerfile ARG/ENV ELECTION_APP_VERSION)."""
    return os.environ.get("ELECTION_APP_VERSION", "dev")


APP_VERSION = _app_version()


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


def create(db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID, title: str) -> Report:
    r = Report(tenant_id=tenant_id, title=title, created_by=user_id)
    db.add(r)
    db.flush()
    return r


def add_version(
    db: Session,
    report: Report,
    *,
    user_id: uuid.UUID,
    body: str,
    source_keys: list[str],
    methodology: str,
    uncertainty: str,
    ai_query_ids: list[str],
    countries: list[str],
    correction_note: str | None = None,
) -> ReportVersion:
    if report.status in ("in_review", "approved"):
        raise _conflict(f"report is {report.status}; withdraw from review before editing")
    if not methodology.strip() or not uncertainty.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "methodology and uncertainty statements are required")
    sources = list(db.scalars(select(Source).where(Source.key.in_(source_keys)))) if source_keys else []
    missing = set(source_keys) - {s.key for s in sources}
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown sources: {sorted(missing)}")
    queries = []
    for qid in ai_query_ids:
        q = db.get(AssistantQuery, uuid.UUID(qid))  # RLS: only this tenant's queries resolve
        if q is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"assistant query {qid} not found")
        queries.append(q)
    if report.status == "published" and not correction_note:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "a correction note is required to revise a " "published report"
        )
    last = max((v.version for v in report.versions), default=0)
    models = {f"{m.kind}:{m.version}" for m in db.scalars(select(ModelVersion))}
    v = ReportVersion(
        tenant_id=report.tenant_id,
        report_id=report.id,
        version=last + 1,
        body_markdown=body,
        sources=[
            {
                "key": s.key,
                "name": s.name,
                "publisher": s.publisher,
                "license": s.license,
                "url": s.homepage_url,
                "is_synthetic": s.is_synthetic,
                "data_kind": s.data_kind,
            }
            for s in sources
        ],
        methodology=methodology,
        uncertainty=uncertainty,
        data_freshness={s.key: source_freshness(s) for s in sources},
        reproducibility={
            "app_version": APP_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "model_versions": sorted(models),
            "assistant_queries": [
                {
                    "id": str(q.id),
                    "provider": q.provider,
                    "model": q.model,
                    "prompt_version": q.prompt_version,
                    "tool_calls": q.tool_calls,
                }
                for q in queries
            ],
            "countries": countries,
        },
        ai_assisted=bool(queries),
        ai_query_ids=[str(q.id) for q in queries],
        contains_synthetic_data=any(s.is_synthetic for s in sources),
        author_id=user_id,
        correction_of_version=report.published_version if correction_note else None,
        correction_note=correction_note,
    )
    db.add(v)
    if report.status in ("changes_requested", "withdrawn"):
        report.status = "draft"
    db.flush()
    db.refresh(report)
    return v


def submit(db: Session, report: Report) -> None:
    if report.status not in ("draft", "published") or not report.versions:
        raise _conflict("only a draft with at least one version can be submitted")
    latest = report.versions[-1]
    if latest.published_at is not None:
        raise _conflict("the latest version is already published; add a correction version first")
    report.status = "in_review"


def review(db: Session, report: Report, *, reviewer_id: uuid.UUID, approve: bool, comment: str) -> None:
    if report.status != "in_review":
        raise _conflict("report is not in review")
    latest = report.versions[-1]
    if latest.author_id == reviewer_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "authors cannot review their own version")
    latest.reviewer_id, latest.review_comment, latest.reviewed_at = reviewer_id, comment, datetime.now(UTC)
    latest.review_decision = "approved" if approve else "changes_requested"
    report.status = "approved" if approve else "changes_requested"


def publication_blockers(db: Session, report: Report, v: ReportVersion) -> list[str]:
    blockers = []
    tenant = db.get(Tenant, report.tenant_id)
    restr = (tenant.publication_restrictions or {}) if tenant else {}
    countries = v.reproducibility.get("countries", [])
    for c in countries:
        if c in restr.get("blocked_countries", []):
            blockers.append(f"organization policy blocks publication about {c}")
        country = db.get(Country, c)
        days = (country.publication_rules or {}).get("poll_publication_blackout_days", 0) if country else 0
        if days and any(s["data_kind"] in ("polls", "synthetic") for s in v.sources):
            upcoming = db.scalar(
                select(Election.election_date)
                .join(ElectionCycle)
                .where(ElectionCycle.country_code == c, Election.election_date >= date.today())
                .order_by(Election.election_date)
                .limit(1)
            )
            if upcoming and upcoming - date.today() <= timedelta(days=days):
                blockers.append(f"{c} poll publication blackout: {days} days before the {upcoming} election")
    if v.contains_synthetic_data and not restr.get("allow_synthetic_publication", False):
        blockers.append("version cites SYNTHETIC demo data; synthetic content cannot be published")
    return blockers


def publish(db: Session, report: Report, *, publisher_id: uuid.UUID) -> ReportVersion:
    if report.status != "approved":
        raise _conflict("only approved reports can be published")
    v = report.versions[-1]
    blockers = publication_blockers(db, report, v)
    if blockers:
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": "publication blocked", "blockers": blockers})
    v.published_at = datetime.now(UTC)
    report.status, report.published_version = "published", v.version
    return v


def _heading(line: str) -> str:
    level = len(line) - len(line.lstrip("#"))
    return f"<h{level}>{html.escape(line.lstrip('# '))}</h{level}>"


def render(report: Report, v: ReportVersion, fmt: str) -> tuple[str, str]:
    meta = {
        "title": report.title,
        "version": v.version,
        "status": report.status,
        "published_at": v.published_at.isoformat() if v.published_at else None,
        "ai_assisted": v.ai_assisted,
        "contains_synthetic_data": v.contains_synthetic_data,
        "correction_of_version": v.correction_of_version,
        "correction_note": v.correction_note,
        "sources": v.sources,
        "methodology": v.methodology,
        "uncertainty": v.uncertainty,
        "data_freshness": v.data_freshness,
        "reproducibility": v.reproducibility,
    }
    banner = []
    if v.contains_synthetic_data:
        banner.append("SYNTHETIC DEMO DATA — not real election data.")
    if v.ai_assisted:
        banner.append(
            "AI-assisted: portions were drafted with the platform research assistant and reviewed by " "a human editor."
        )
    if v.published_at is None:
        banner.append("DRAFT — not published.")
    if fmt == "json":
        import json  # noqa: PLC0415

        return json.dumps(
            {**meta, "body_markdown": v.body_markdown, "notices": banner}, default=str, indent=2
        ), "application/json"
    src_md = "\n".join(f"- {s['name']} — {s['publisher']} ({s['license']}) {s['url']}" for s in v.sources) or "- none"
    md = (
        f"# {report.title}\n\n"
        + "".join(f"> **{b}**\n" for b in banner)
        + (f"\n> Correction to version {v.correction_of_version}: {v.correction_note}\n" if v.correction_note else "")
        + f"\n{v.body_markdown}\n\n## Methodology\n\n{v.methodology}\n\n## Uncertainty\n\n{v.uncertainty}\n\n"
        f"## Sources\n\n{src_md}\n\n## Data freshness\n\n"
        + "\n".join(f"- {k}: {f['state']} (last success {f['last_success_at']})" for k, f in v.data_freshness.items())
        + f"\n\n## Reproducibility\n\n- App version: {v.reproducibility.get('app_version')}\n"
        f"- Generated: {v.reproducibility.get('generated_at')}\n"
        f"- Models: {', '.join(v.reproducibility.get('model_versions', []))}\n"
        f"- Assistant queries: {', '.join(q['id'] for q in v.reproducibility.get('assistant_queries', [])) or 'none'}\n"
        f"- Content SHA-256: {hashlib.sha256(v.body_markdown.encode()).hexdigest()}\n"
    )
    if fmt == "md":
        return md, "text/markdown"
    body = "".join(
        f"<p>{html.escape(line)}</p>" if line and not line.startswith("#") else (_heading(line) if line else "")
        for line in md.splitlines()
    )
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{html.escape(report.title)}</title>"
        f"</head><body>{body}</body></html>"
    ), "text/html"
