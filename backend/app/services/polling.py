"""Poll listings and a transparent polling average.

Uncertainty rules (docs/methodology/polling.md):
  * Probability samples: show the pollster's published MOE; if none, an *approximate*
    MOE assuming simple random sampling, inflated by a published design effect if any,
    and labelled as such.
  * Nonprobability / unknown designs: no margin of error is shown or computed.
  * The average reports the spread of included polls, not a sampling margin.
Overlap rule: within a tracking series, field periods that overlap share respondents;
only the most recent non-overlapping releases are included, and exclusions are listed.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Party, Poll, PollQuestion, Source

POP_LABEL = {"a": "All adults", "rv": "Registered voters", "lv": "Likely voters", "v": "Voters"}


def poll_uncertainty(p: Poll) -> dict:
    if p.sampling_method != "probability":
        return {
            "kind": "none",
            "label": "No margin of error: not a probability sample"
            + (" (pollster's published figure not shown as a sampling MOE)" if p.published_moe else ""),
        }
    if p.published_moe is not None:
        return {"kind": "published", "moe": p.published_moe, "label": f"±{p.published_moe} pts (as published)"}
    if p.sample_size:
        deff = p.design_effect or 1.0
        moe = round(100 * 1.96 * math.sqrt(0.25 * deff / p.sample_size), 1)
        return {
            "kind": "approximate",
            "moe": moe,
            "label": f"≈±{moe} pts (approximate; assumes simple random "
            f"sampling{' with published design effect' if p.design_effect else ', ignores weighting'})",
        }
    return {"kind": "none", "label": "Sample size not published"}


def poll_view(p: Poll, sources: dict, parties: dict) -> dict:
    src = sources.get(p.source_id)
    return {
        "id": str(p.id),
        "pollster": p.pollster.name,
        "sponsor": p.sponsor,
        "sponsor_is_partisan": p.sponsor_is_partisan,
        "field_start": p.field_start,
        "field_end": p.field_end,
        "population": p.population,
        "population_label": POP_LABEL[p.population],
        "sample_size": p.sample_size,
        "mode": p.mode,
        "sampling_method": p.sampling_method,
        "weighting": p.weighting,
        "methodology_url": p.methodology_url,
        "questionnaire_url": p.questionnaire_url,
        "tracking_series": p.tracking_series,
        "question_scope": p.question_scope,
        "uncertainty": poll_uncertainty(p),
        "tenant_private": p.tenant_id is not None,
        "source": {"key": src.key, "name": src.name, "is_synthetic": src.is_synthetic} if src else None,
        "questions": [
            {
                "wording": q.wording,
                "topic": q.topic,
                "results": [
                    {
                        "choice": r.choice,
                        "pct": r.pct,
                        "subgroup": r.subgroup,
                        "party": parties[r.party_id].abbreviation if r.party_id in parties else None,
                    }
                    for r in q.results
                ],
            }
            for q in p.questions
        ],
    }


def list_polls(db: Session, *, country: str, scope: str | None = None, contest_id=None, limit: int = 200) -> list[dict]:  # type: ignore[no-untyped-def]
    q = (
        select(Poll)
        .where(Poll.country_code == country)
        .options(selectinload(Poll.pollster), selectinload(Poll.questions).selectinload(PollQuestion.results))
    )
    if scope:
        q = q.where(Poll.question_scope == scope)
    if contest_id:
        q = q.where(Poll.contest_id == contest_id)
    polls = db.scalars(q.order_by(Poll.field_end.desc()).limit(limit)).all()
    sources = {s.id: s for s in db.scalars(select(Source))}
    parties = {p.id: p for p in db.scalars(select(Party))}
    return [poll_view(p, sources, parties) for p in polls]


def select_non_overlapping(polls: list[Poll]) -> tuple[list[Poll], list[dict]]:
    kept, excluded = [], []
    by_series: dict[str | None, list[Poll]] = defaultdict(list)
    for p in polls:
        by_series[p.tracking_series].append(p)
    for series, items in by_series.items():
        if series is None:
            kept.extend(items)
            continue
        chosen: list[Poll] = []
        for p in sorted(items, key=lambda x: x.field_end, reverse=True):
            clash = next((c for c in chosen if p.field_start <= c.field_end and c.field_start <= p.field_end), None)
            if clash:
                excluded.append(
                    {
                        "poll_id": str(p.id),
                        "reason": f"field period overlaps a later release in tracking "
                        f"series '{series}' ({clash.field_start}–{clash.field_end})",
                    }
                )
            else:
                chosen.append(p)
        kept.extend(chosen)
    return kept, excluded


def _fetch(db: Session, country: str, scope: str, lo: date, hi: date, contest_id=None) -> list[Poll]:  # type: ignore[no-untyped-def]
    q = (
        select(Poll)
        .where(Poll.country_code == country, Poll.question_scope == scope, Poll.field_end <= hi, Poll.field_end > lo)
        .options(selectinload(Poll.pollster), selectinload(Poll.questions).selectinload(PollQuestion.results))
    )
    if contest_id:
        q = q.where(Poll.contest_id == contest_id)
    return list(db.scalars(q))


def average(
    db: Session,
    *,
    country: str,
    scope: str = "generic_ballot",
    as_of: date,
    window_days: int = 60,
    half_life_days: float = 14.0,
    contest_id=None,  # type: ignore[no-untyped-def]
    polls: list[Poll] | None = None,
    synthetic_sources: set | None = None,
) -> dict:
    """Recency- and size-weighted average using only polls whose field period ended by `as_of`.

    `polls` may be a superset fetched once by the caller (e.g. for a trend); it is filtered here.
    """
    lo = date.fromordinal(as_of.toordinal() - window_days)
    if polls is None:
        polls = _fetch(db, country, scope, lo, as_of, contest_id)
    polls = [p for p in polls if lo < p.field_end <= as_of]
    if synthetic_sources is None:
        synthetic_sources = {s.id for s in db.scalars(select(Source).where(Source.is_synthetic.is_(True)))}
    kept, excluded = select_non_overlapping(polls)
    pop_pref = {"lv": 1.0, "rv": 0.85, "v": 1.0, "a": 0.6}
    sums: dict[str, float] = defaultdict(float)
    values: dict[str, list[tuple[float, float]]] = defaultdict(list)
    wsum = 0.0
    for p in kept:
        age = (as_of - p.field_end).days
        w = 0.5 ** (age / half_life_days) * math.sqrt(min(p.sample_size or 400, 3000)) * pop_pref[p.population]
        w *= 0.5 if p.sponsor_is_partisan else 1.0
        res = [r for qq in p.questions for r in qq.results if r.subgroup == "all"]
        if not res:
            continue
        wsum += w
        for r in res:
            sums[r.choice] += w * r.pct
            values[r.choice].append((w, r.pct))
    if not kept or wsum == 0:
        return {
            "available": False,
            "reason": "No eligible polls in the window.",
            "as_of": as_of,
            "n_polls": 0,
            "excluded": excluded,
        }
    est = {}
    for choice, s in sums.items():
        mean = s / wsum
        sd = math.sqrt(sum(w * (v - mean) ** 2 for w, v in values[choice]) / sum(w for w, _ in values[choice]))
        est[choice] = {"mean": round(mean, 2), "spread_sd": round(sd, 2), "n_polls": len(values[choice])}
    return {
        "available": True,
        "as_of": as_of,
        "window_days": window_days,
        "half_life_days": half_life_days,
        "n_polls": len(kept),
        "estimates": est,
        "excluded": excluded,
        "uses_synthetic_data": any(p.source_id in synthetic_sources for p in kept),
        "method": f"Exponential recency weights (half-life {half_life_days}d) × √n (capped at 3000) × "
        "population preference "
        "(LV/V 1.0, RV 0.85, adults 0.6) × 0.5 for partisan sponsors. Spread is the weighted SD across "
        "polls — it is not a margin of error.",
    }


def trend(db: Session, *, country: str, scope: str, as_of: date, window_days: int, step_days: int = 7) -> list[dict]:
    """Averages recomputed every `step_days`, from a single poll fetch."""
    points = [date.fromordinal(as_of.toordinal() - k) for k in range(0, window_days, step_days)]
    polls = _fetch(db, country, scope, date.fromordinal(points[-1].toordinal() - window_days), as_of)
    synth = {s.id for s in db.scalars(select(Source).where(Source.is_synthetic.is_(True)))}
    out = []
    for d in reversed(points):
        a = average(
            db, country=country, scope=scope, as_of=d, window_days=window_days, polls=polls, synthetic_sources=synth
        )
        if a["available"]:
            out.append({"as_of": d, **{c: v["mean"] for c, v in a["estimates"].items()}})
    return out
