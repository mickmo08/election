"""Results, polling, surveys, issue analysis, forecasts, assistant records and reports."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, created_at, uuid_pk

# --------------------------------------------------------------------------- results

RESULT_STATUSES = ("preliminary", "unofficial", "certified", "corrected", "recount")


class ResultSnapshot(Base):
    """One immutable observation of a contest's results from one source at one time.

    Snapshots are never updated. Corrections and recounts are new snapshots that
    reference the snapshot they supersede, so the full history is preserved.
    """

    __tablename__ = "result_snapshots"
    __table_args__ = (
        CheckConstraint(f"status IN {RESULT_STATUSES}", name="status"),
        CheckConstraint("reporting_pct IS NULL OR (reporting_pct >= 0 AND reporting_pct <= 100)", name="pct"),
        CheckConstraint("reporting_supported OR reporting_pct IS NULL", name="reporting_only_if_supported"),
        UniqueConstraint("contest_id", "source_id", "content_hash"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    contest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contests.id"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    raw_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_files.id"))
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    status: Mapped[str] = mapped_column(String(16))
    source_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # publisher timestamp
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reporting_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    reporting_pct: Mapped[float | None] = mapped_column(Float)
    total_votes: Mapped[int | None] = mapped_column(BigInteger)
    eligible_or_registered: Mapped[int | None] = mapped_column(BigInteger)
    turnout_denominator_kind: Mapped[str | None] = mapped_column(String(32))  # registered, vep, vap
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("result_snapshots.id"))
    correction_note: Mapped[str | None] = mapped_column(Text)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False)
    dispute_note: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    lines: Mapped[list[ResultLine]] = relationship(back_populates="snapshot", order_by="ResultLine.votes.desc()")
    created_at = created_at()


class ResultLine(Base):
    __tablename__ = "result_lines"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("result_snapshots.id"), index=True)
    candidacy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("candidacies.id"))
    label: Mapped[str] = mapped_column(String(300))  # as published by the source
    party_label: Mapped[str | None] = mapped_column(String(200))
    votes: Mapped[int] = mapped_column(BigInteger)
    is_writein: Mapped[bool] = mapped_column(Boolean, default=False)
    snapshot: Mapped[ResultSnapshot] = relationship(back_populates="lines")


class RaceCall(Base):
    """A race call attributed to an authorised source under the editorial policy.

    The assistant and any model have no write path to this table.
    """

    __tablename__ = "race_calls"
    id: Mapped[uuid.UUID] = uuid_pk()
    contest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contests.id"), index=True)
    candidacy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidacies.id"))
    caller_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="called")  # called, retracted
    note: Mapped[str] = mapped_column(Text, default="")
    recorded_by: Mapped[str] = mapped_column(String(200))
    created_at = created_at()


# --------------------------------------------------------------------------- polling

POPULATIONS = ("a", "rv", "lv", "v")  # all adults, registered voters, likely voters, voters
SAMPLING = ("probability", "nonprobability", "mixed", "unknown")


class Pollster(Base):
    __tablename__ = "pollsters"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(300), unique=True)
    transparency_notes: Mapped[str] = mapped_column(Text, default="")


class Poll(Base):
    __tablename__ = "polls"
    __table_args__ = (
        CheckConstraint(f"population IN {POPULATIONS}", name="population"),
        CheckConstraint(f"sampling_method IN {SAMPLING}", name="sampling"),
        CheckConstraint("field_end >= field_start", name="field_dates"),
        CheckConstraint("sample_size IS NULL OR sample_size > 0", name="sample_size"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    pollster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pollsters.id"))
    sponsor: Mapped[str | None] = mapped_column(String(300))
    sponsor_is_partisan: Mapped[bool] = mapped_column(Boolean, default=False)
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"))
    admin_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_units.id"))
    contest_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contests.id"), index=True)
    question_scope: Mapped[str] = mapped_column(String(64))  # contest, generic_ballot, approval, issue
    field_start: Mapped[date] = mapped_column(Date)
    field_end: Mapped[date] = mapped_column(Date)
    population: Mapped[str] = mapped_column(String(4))
    sample_size: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(100))  # live phone, online panel, text-to-web, mixed...
    sampling_method: Mapped[str] = mapped_column(String(32))
    weighting: Mapped[str] = mapped_column(Text, default="")
    methodology_url: Mapped[str | None] = mapped_column(Text)
    questionnaire_url: Mapped[str | None] = mapped_column(Text)
    published_moe: Mapped[float | None] = mapped_column(Float)  # only as published by the pollster
    design_effect: Mapped[float | None] = mapped_column(Float)
    # Polls in the same panel/tracking series whose field periods overlap share respondents.
    tracking_series: Mapped[str | None] = mapped_column(String(200))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    raw_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_files.id"))
    created_at = created_at()
    pollster: Mapped[Pollster] = relationship()
    questions: Mapped[list[PollQuestion]] = relationship(back_populates="poll")


class PollQuestion(Base):
    __tablename__ = "poll_questions"
    id: Mapped[uuid.UUID] = uuid_pk()
    poll_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("polls.id"), index=True)
    wording: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(100))
    poll: Mapped[Poll] = relationship(back_populates="questions")
    results: Mapped[list[PollResult]] = relationship(back_populates="question")


class PollResult(Base):
    __tablename__ = "poll_results"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("poll_questions.id"), index=True)
    choice: Mapped[str] = mapped_column(String(300))
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"))
    candidacy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("candidacies.id"))
    pct: Mapped[float] = mapped_column(Float)
    subgroup: Mapped[str] = mapped_column(String(100), default="all")
    question: Mapped[PollQuestion] = relationship(back_populates="results")


class SurveyDataset(Base):
    """A de-identified, consent-based survey upload owned by one tenant.

    Respondent-level rows are never returned by any API; only suppressed aggregates.
    """

    __tablename__ = "survey_datasets"
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    consent_basis: Mapped[str] = mapped_column(Text)
    deidentification_attestation: Mapped[str] = mapped_column(Text)
    attested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    sampling_method: Mapped[str] = mapped_column(String(32))
    population: Mapped[str] = mapped_column(String(4))
    weight_column: Mapped[str | None] = mapped_column(String(100))
    columns: Mapped[list] = mapped_column(JSONB, default=list)
    n_rows: Mapped[int] = mapped_column(Integer)
    raw_sha256: Mapped[str] = mapped_column(String(64))
    field_start: Mapped[date | None] = mapped_column(Date)
    field_end: Mapped[date | None] = mapped_column(Date)
    created_at = created_at()


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("survey_datasets.id"), index=True)
    answers: Mapped[dict] = mapped_column(JSONB)
    weight: Mapped[float] = mapped_column(Float, default=1.0)


# --------------------------------------------------------------------------- issues

class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("kind", "version"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(64))  # topic_classifier, forecast, assistant_prompt
    version: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at = created_at()


class Document(Base):
    """A news article or public-discussion item from a source that permits text analysis."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(32))  # news, public_discussion
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    language: Mapped[str] = mapped_column(String(16))
    languages_detected: Mapped[dict] = mapped_column(JSONB, default=dict)
    country_code: Mapped[str | None] = mapped_column(ForeignKey("countries.code"))
    admin_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_units.id"))
    geo_confidence: Mapped[str] = mapped_column(String(16), default="none")  # none, low, medium, high
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    minhash: Mapped[list] = mapped_column(JSONB, default=list)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    raw_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_files.id"))
    created_at = created_at()


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("taxonomy_version", "key"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


class DocumentTopic(Base):
    __tablename__ = "document_topics"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float)


class TopicLabel(Base):
    """Human review label; the gold standard for evaluating the classifier."""

    __tablename__ = "topic_labels"
    __table_args__ = (UniqueConstraint("document_id", "topic_id", "reviewer"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))
    is_relevant: Mapped[bool] = mapped_column(Boolean)
    reviewer: Mapped[str] = mapped_column(String(200))
    split: Mapped[str] = mapped_column(String(16), default="eval")  # eval, dev
    created_at = created_at()


# --------------------------------------------------------------------------- forecasts

FORECAST_STATUSES = ("draft", "blocked", "validated", "published", "withdrawn")


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (CheckConstraint(f"status IN {FORECAST_STATUSES}", name="status"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"))
    office_key: Mapped[str] = mapped_column(String(64))
    cycle_key: Mapped[str] = mapped_column(String(64))
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id"))
    kind: Mapped[str] = mapped_column(String(16), default="forecast")  # forecast, scenario
    scenario: Mapped[dict | None] = mapped_column(JSONB)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    gate_results: Mapped[list] = mapped_column(JSONB, default=list)
    assumptions: Mapped[list] = mapped_column(JSONB, default=list)
    inputs_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    contest_outputs: Mapped[list] = mapped_column(JSONB, default=list)
    aggregate_outputs: Mapped[dict] = mapped_column(JSONB, default=dict)
    backtest: Mapped[dict] = mapped_column(JSONB, default=dict)
    uses_synthetic_data: Mapped[bool] = mapped_column(Boolean, default=False)
    random_seed: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at = created_at()


# --------------------------------------------------------------------------- assistant

class AssistantQuery(Base):
    __tablename__ = "assistant_queries"
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    tool_calls: Mapped[list] = mapped_column(JSONB, default=list)
    answer: Mapped[str] = mapped_column(Text, default="")
    claims: Mapped[list] = mapped_column(JSONB, default=list)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_warnings: Mapped[list] = mapped_column(JSONB, default=list)
    grounding: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32))  # answered, refused, insufficient_evidence, error
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at = created_at()


# --------------------------------------------------------------------------- reports

REPORT_STATUSES = ("draft", "in_review", "changes_requested", "approved", "published", "withdrawn")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (CheckConstraint(f"status IN {REPORT_STATUSES}", name="status"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    published_version: Mapped[int | None] = mapped_column(Integer)
    created_at = created_at()
    versions: Mapped[list[ReportVersion]] = relationship(order_by="ReportVersion.version")


class ReportVersion(Base):
    __tablename__ = "report_versions"
    __table_args__ = (UniqueConstraint("report_id", "version"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body_markdown: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    methodology: Mapped[str] = mapped_column(Text, default="")
    uncertainty: Mapped[str] = mapped_column(Text, default="")
    data_freshness: Mapped[dict] = mapped_column(JSONB, default=dict)
    reproducibility: Mapped[dict] = mapped_column(JSONB, default=dict)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_query_ids: Mapped[list] = mapped_column(JSONB, default=list)
    contains_synthetic_data: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    review_decision: Mapped[str | None] = mapped_column(String(32))
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correction_of_version: Mapped[int | None] = mapped_column(Integer)
    correction_note: Mapped[str | None] = mapped_column(Text)
    created_at = created_at()
