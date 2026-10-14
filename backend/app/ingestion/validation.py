"""Reusable validation rules. Each returns Issues; adapters decide blocking vs record-level."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable
from datetime import date, datetime

from .framework import Issue, StructuralError


def read_csv(content: bytes, required: Iterable[str], ref: str = "file") -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 decodes all bytes
            raise StructuralError([Issue(ref, "encoding", f"undecodable file: {exc}", blocking=True)]) from exc
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in header]
    if missing:
        raise StructuralError(
            [
                Issue(
                    ref,
                    "schema",
                    f"missing required columns: {', '.join(missing)}",
                    blocking=True,
                    suggested_action="Confirm the publisher has not changed the file layout; update the adapter "
                    "schema version if it has.",
                    payload={"header": header},
                )
            ]
        )
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def parse_int(value: str, field: str, ref: str, issues: list[Issue], *, minimum: int = 0) -> int | None:
    try:
        v = int(float(value.replace(",", ""))) if value not in ("", "NA") else None
    except ValueError:
        issues.append(Issue(ref, "type", f"{field}={value!r} is not a number"))
        return None
    if v is not None and v < minimum:
        issues.append(Issue(ref, "range", f"{field}={v} is below {minimum}"))
        return None
    return v


def parse_float(
    value: str, field: str, ref: str, issues: list[Issue], lo: float | None = None, hi: float | None = None
) -> float | None:
    if value in ("", "NA", None):
        return None
    try:
        v = float(value)
    except ValueError:
        issues.append(Issue(ref, "type", f"{field}={value!r} is not a number"))
        return None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        issues.append(Issue(ref, "range", f"{field}={v} outside [{lo}, {hi}]"))
        return None
    return v


def parse_date(value: str, field: str, ref: str, issues: list[Issue]) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.append(Issue(ref, "type", f"{field}={value!r} is not an ISO date (YYYY-MM-DD)"))
        return None


def parse_datetime(value: str, field: str, ref: str, issues: list[Issue]) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        issues.append(Issue(ref, "type", f"{field}={value!r} is not an ISO timestamp"))
        return None
    if dt.tzinfo is None:
        issues.append(Issue(ref, "timezone", f"{field} has no timezone offset"))
        return None
    return dt


def parse_bool(value: str) -> bool:
    return value.strip().upper() in ("TRUE", "T", "1", "YES", "Y")


def check_totals(lines_sum: int, reported_total: int | None, ref: str, tolerance: float = 0.0) -> Issue | None:
    """Candidate votes must not exceed the reported total; they should equal it when the
    total covers only candidate votes (adapters choose tolerance)."""
    if reported_total is None:
        return None
    if lines_sum > reported_total:
        return Issue(
            ref,
            "totals",
            f"candidate votes {lines_sum} exceed reported total {reported_total}",
            suggested_action="Check for duplicated rows or fusion-ticket double counting.",
        )
    if reported_total and (reported_total - lines_sum) / reported_total > tolerance:
        return Issue(
            ref,
            "totals",
            f"candidate votes {lines_sum} are below reported total {reported_total} by " f"more than {tolerance:.1%}",
            severity="warning",
            suggested_action="Usually blank/over/under votes or unlisted candidates; confirm with publisher.",
        )
    return None


def content_hash(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
