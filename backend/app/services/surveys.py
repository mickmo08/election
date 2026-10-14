"""De-identified, consent-based survey microdata: import and disclosure-controlled aggregates.

Respondent-level rows are never returned by any endpoint. Aggregates suppress cells with
fewer than `survey_min_cell_size` unweighted respondents (and the complementary cell when
only one cell in a row would be suppressed, to prevent recovery by subtraction).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import SurveyDataset, SurveyResponse

DIRECT_IDENTIFIERS = re.compile(
    r"^(name|first_?name|last_?name|full_?name|email|e_?mail|phone|mobile|address|street|ssn|social_security|"
    r"ip|ip_?address|dob|date_?of_?birth|birth_?date|latitude|longitude|lat|lon|lng|voter_?id|"
    r"respondent_?name|device_?id|user_?id|panelist_?id|zip|zipcode|postal_?code)$", re.I)
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\-\s().]{8,}\d")
MAX_ROWS = 200_000


def import_survey(db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID, name: str, content: bytes,
                  consent_basis: str, deidentification_attestation: str, sampling_method: str, population: str,
                  weight_column: str | None) -> SurveyDataset:
    if len(consent_basis.strip()) < 20 or len(deidentification_attestation.strip()) < 20:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "consent basis and de-identification attestation must be described (>= 20 characters)")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "file must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    cols = [c.strip() for c in reader.fieldnames or []]
    bad = [c for c in cols if DIRECT_IDENTIFIERS.match(c)]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"direct or quasi-identifier columns are not accepted: {bad}. Remove them before upload.")
    if weight_column and weight_column not in cols:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"weight column {weight_column!r} not found")
    rows = []
    for i, row in enumerate(reader):
        if i >= MAX_ROWS:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"more than {MAX_ROWS} rows")
        for v in row.values():
            if v and (EMAIL_RE.search(v) or PHONE_RE.fullmatch(v.strip())):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"row {i + 2} contains a value that looks like an email or phone number")
        w = 1.0
        if weight_column:
            try:
                w = float(row[weight_column])
            except (TypeError, ValueError) as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"row {i + 2}: invalid weight") from exc
            if w <= 0:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"row {i + 2}: weight must be > 0")
        rows.append(({k.strip(): (v or "").strip() for k, v in row.items() if k != weight_column}, w))
    if not rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no rows")
    ds = SurveyDataset(tenant_id=tenant_id, name=name, consent_basis=consent_basis,
                       deidentification_attestation=deidentification_attestation, attested_by=user_id,
                       sampling_method=sampling_method, population=population, weight_column=weight_column,
                       columns=[c for c in cols if c != weight_column], n_rows=len(rows),
                       raw_sha256=hashlib.sha256(content).hexdigest())
    db.add(ds)
    db.flush()
    db.execute(insert(SurveyResponse), [{"tenant_id": tenant_id, "dataset_id": ds.id, "answers": a, "weight": w}
                                        for a, w in rows])
    return ds


def crosstab(db: Session, dataset_id: uuid.UUID, row_var: str, col_var: str | None = None) -> dict:
    ds = db.get(SurveyDataset, dataset_id)  # RLS ensures only the owning tenant can see it
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    for v in (row_var, col_var):
        if v and v not in ds.columns:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown variable {v!r}")
    k = get_settings().survey_min_cell_size
    counts: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    for answers, weight in db.execute(select(SurveyResponse.answers, SurveyResponse.weight)
                                      .where(SurveyResponse.dataset_id == dataset_id)):
        col = answers.get(col_var, "") if col_var else "All"
        cell = counts[col][answers.get(row_var, "")]
        cell[0] += 1
        cell[1] += weight
    out_cols = {}
    for col, cells in counts.items():
        col_n = sum(c[0] for c in cells.values())
        col_w = sum(c[1] for c in cells.values())
        if col_n < k:
            out_cols[col] = {"suppressed": True, "reason": f"column base n<{k}"}
            continue
        small = {val for val, c in cells.items() if c[0] < k}
        if len(small) == 1 and len(cells) > 1:  # complementary suppression
            small.add(min((v for v in cells if v not in small), key=lambda v: cells[v][0]))
        out_cols[col] = {
            "suppressed": False, "base_n_band": _band(col_n),
            "cells": {val: ({"suppressed": True} if val in small else
                            {"suppressed": False, "weighted_pct": round(100 * c[1] / col_w, 1)})
                      for val, c in sorted(cells.items())},
        }
    return {"dataset": {"id": str(ds.id), "name": ds.name, "sampling_method": ds.sampling_method,
                        "population": ds.population, "weighted": bool(ds.weight_column)},
            "row_var": row_var, "col_var": col_var, "min_cell_size": k, "columns": out_cols,
            "uncertainty": ("Probability sample: interpret differences with sampling error in mind."
                            if ds.sampling_method == "probability" else
                            "Not a probability sample: no margin of error applies; results describe respondents only."),
            "notes": "Respondent-level data is never exposed. Bases are reported in bands."}


def _band(n: int) -> str:
    for lo, hi in ((30, 99), (100, 249), (250, 499), (500, 999), (1000, 2499)):
        if lo <= n <= hi:
            return f"{lo}–{hi}"
    return "2500+" if n >= 2500 else f"<30"
