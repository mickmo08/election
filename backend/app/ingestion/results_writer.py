"""Append-only result snapshot writer with status-transition and correction rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..models import Candidacy, Contest, ResultLine, ResultSnapshot
from .framework import Issue, RunContext
from .validation import content_hash

STATUS_RANK = {"preliminary": 0, "unofficial": 1, "certified": 2, "recount": 3, "corrected": 3}


@dataclass
class Line:
    label: str
    votes: int
    party_label: str | None = None
    candidacy: Candidacy | None = None
    is_writein: bool = False


def latest_snapshot(db: Session, contest_id, source_id=None) -> ResultSnapshot | None:  # type: ignore[no-untyped-def]
    q = select(ResultSnapshot).where(ResultSnapshot.contest_id == contest_id)
    if source_id is not None:
        q = q.where(ResultSnapshot.source_id == source_id)
    return db.scalar(q.order_by(ResultSnapshot.retrieved_at.desc(), ResultSnapshot.created_at.desc()).limit(1))


def write_snapshot(ctx: RunContext, contest: Contest, *, status: str, lines: list[Line], retrieved_at: datetime,
                   raw_file_id, record_ref: str, total_votes: int | None = None,  # type: ignore[no-untyped-def]
                   source_as_of: datetime | None = None, reporting_pct: float | None = None,
                   reporting_supported: bool = False, correction_note: str | None = None,
                   eligible: int | None = None, denominator_kind: str | None = None) -> ResultSnapshot | None:
    db = ctx.db
    if not reporting_supported and reporting_pct is not None:
        reporting_pct = None  # never display completeness the source does not support
    payload = sorted((ln.label, ln.party_label or "", ln.votes) for ln in lines)
    chash = content_hash({"status": status, "lines": payload, "total": total_votes, "pct": reporting_pct,
                          "as_of": source_as_of})
    prev = latest_snapshot(db, contest.id, ctx.source.id)
    if prev is not None:
        if prev.content_hash == chash:
            ctx.count("snapshots_unchanged")
            return None
        if prev.status == "certified" and status not in ("corrected", "recount", "certified"):
            ctx.quarantine(Issue(record_ref, "status_regression",
                                 f"{contest.name}: source reports '{status}' after a certified result",
                                 suggested_action="Confirm with the publisher; certified results may only be "
                                                  "superseded by a correction or recount."))
            return None
        if prev.status == "certified" and status == "certified":
            ctx.quarantine(Issue(record_ref, "certified_changed",
                                 f"{contest.name}: certified totals changed without a correction/recount status",
                                 suggested_action="Re-label as 'corrected' with a correction note if the "
                                                  "publisher issued an amended canvass."))
            return None
        if status in ("preliminary", "unofficial") and prev.status == status and total_votes is not None \
                and prev.total_votes is not None and total_votes < prev.total_votes:
            ctx.quarantine(Issue(record_ref, "count_decreased",
                                 f"{contest.name}: total votes decreased {prev.total_votes} -> {total_votes}",
                                 severity="warning", suggested_action="Often a publisher correction; verify."))
    if status in ("corrected", "recount") and not correction_note:
        correction_note = f"{status} reported by {ctx.source.publisher}"
    snap = ResultSnapshot(
        contest_id=contest.id, source_id=ctx.source.id, raw_file_id=raw_file_id, ingestion_run_id=ctx.run.id,
        status=status, source_as_of=source_as_of, retrieved_at=retrieved_at, reporting_supported=reporting_supported,
        reporting_pct=reporting_pct, total_votes=total_votes if total_votes is not None else sum(ln.votes for ln in lines),
        supersedes_id=prev.id if prev else None, correction_note=correction_note, content_hash=chash,
        eligible_or_registered=eligible, turnout_denominator_kind=denominator_kind if eligible else None,
    )
    db.add(snap)
    db.flush()
    db.execute(insert(ResultLine), [
        {"snapshot_id": snap.id, "candidacy_id": ln.candidacy.id if ln.candidacy else None, "label": ln.label,
         "party_label": ln.party_label, "votes": ln.votes, "is_writein": ln.is_writein} for ln in lines])
    ctx.count("snapshots_written")
    return snap
