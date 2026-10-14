"""Forecast runs: backtests, publication gates, scenarios and publication."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import Election, ElectionCycle, ForecastRun, ModelVersion, Office
from . import model as M
from .data import cycle_inputs

GATES = {
    "min_backtest_cycles": 3,
    "max_ece": 0.08,
    "coverage_80_range": (0.70, 0.92),
    "min_brier_skill_vs_persistence": 0.0,
    "min_prior_coverage": 0.80,
    "min_polls": 3,
    "min_seat_interval_hit_rate": 0.6,
}

ASSUMPTIONS = [
    "Two-party framing: margin = (A − B)/(A + B) between the country's two largest parties; other parties are "
    "not modelled and contests without both parties are handled deterministically and flagged.",
    "District margins follow last comparable result, incumbency and the change in the national poll environment.",
    "Errors = shared national shock (Student-t) + independent district error, both estimated from earlier cycles.",
    "Prior results are used only where boundaries are identical or a population crosswalk exists; otherwise "
    "uncertainty is inflated by 1.5×.",
    "Polls enter only if fieldwork ended at least one day before the data cutoff.",
    "Historical results use the final values on record, which can include post-cutoff corrections.",
    "This is not a prediction of certainty; probabilities describe model uncertainty given the stated inputs.",
]


def _office_cycles(db: Session, country: str, office_key: str) -> list[tuple[int, date]]:
    office = db.scalar(select(Office).where(Office.country_code == country, Office.key == office_key))
    if office is None:
        return []
    from ...models import Contest  # noqa: PLC0415

    rows = db.execute(select(ElectionCycle.year, Election.election_date).join(Election).join(Contest).where(
        ElectionCycle.country_code == country, Contest.office_id == office.id, Election.kind == "general")
        .distinct()).all()
    return sorted({(y, d) for y, d in rows})


def _training(db: Session, country: str, office_key: str, cycles: list[tuple[int, date]], target_year: int,
              outcome_cutoff: date) -> list:
    train = []
    for y, d in cycles:
        if y >= target_year or d >= outcome_cutoff:
            continue
        ci = cycle_inputs(db, country=country, office_key=office_key, year=y, cutoff=M.cutoff_for(d),
                          outcome_cutoff=outcome_cutoff)
        if any(r.margin is not None and r.prev_margin is not None for r in ci.rows):
            train.append(ci)
    return train


def backtest(db: Session, country: str, office_key: str, before_year: int) -> dict:
    """Time-respecting evaluation: for each held-out cycle t < before_year, train on cycles < t only."""
    cycles = _office_cycles(db, country, office_key)
    per_cycle = []
    pooled: dict[str, list] = {"model": [], "persistence": [], "uniform_swing": []}
    outcomes_all: dict[str, float] = {}
    for y, d in cycles:
        if y >= before_year:
            continue
        cut = M.cutoff_for(d)
        train = _training(db, country, office_key, cycles, y, cut)
        if len({t.year for t in train}) < M.MIN_TRAIN_CYCLES:
            continue
        try:
            fitted = M.fit(train)
        except ValueError:
            continue
        target = cycle_inputs(db, country=country, office_key=office_key, year=y, cutoff=cut)
        assert all(r.margin is None for r in target.rows), "leakage: target outcome visible at cutoff"
        truth = cycle_inputs(db, country=country, office_key=office_key, year=y, cutoff=cut,
                             outcome_cutoff=date.max)
        outcomes = {str(r.contest_id): r.margin for r in truth.rows if r.margin is not None and r.has_a and r.has_b}
        preds = {"model": M.predict(fitted, target), "persistence": M.baseline_persistence(fitted, target),
                 "uniform_swing": M.baseline_uniform_swing(fitted, target)}
        sim = M.simulate(fitted, preds["model"], target, None, seed=y)
        actual_seats = sum(1 for r in truth.rows if r.margin is not None and r.margin > 0)
        per_cycle.append({
            "cycle": y, "cutoff": cut, "train_cycles": fitted.train_cycles, "n_contests": len(outcomes),
            "polls_used": target.n_polls,
            "scores": {k: M.score(v, outcomes) for k, v in preds.items()},
            "calibration_ece": M.calibration(preds["model"], outcomes)["ece"],
            "seats_a_predicted_median": sim["seats_a"]["median"], "seats_a_p10_p90": [sim["seats_a"]["p10"],
                                                                                     sim["seats_a"]["p90"]],
            "seats_a_actual": actual_seats,
        })
        for k, v in preds.items():
            pooled[k].extend(v)
        outcomes_all.update(outcomes)
    pooled_scores = {k: M.score(v, outcomes_all) for k, v in pooled.items()}
    cal = M.calibration(pooled["model"], outcomes_all)
    bs_m, bs_p = pooled_scores["model"]["brier"], pooled_scores["persistence"]["brier"]
    return {
        "method": "Expanding-window, time-respecting backtest; cutoff = election day − %d days" % M.LEAD_DAYS,
        "cycles": per_cycle, "pooled": pooled_scores, "calibration": cal,
        "brier_skill_vs_persistence": (1 - bs_m / bs_p) if bs_m is not None and bs_p else None,
        "brier_skill_vs_uniform_swing": (1 - bs_m / pooled_scores["uniform_swing"]["brier"])
        if bs_m is not None and pooled_scores["uniform_swing"]["brier"] else None,
    }


def evaluate_gates(bt: dict, target_rows: list, n_polls: int, synthetic: bool) -> list[dict]:
    g = []
    n_cycles = len(bt["cycles"])
    g.append({"gate": "backtest_cycles", "passed": n_cycles >= GATES["min_backtest_cycles"],
              "detail": f"{n_cycles} held-out cycles (need ≥ {GATES['min_backtest_cycles']})"})
    skill = bt.get("brier_skill_vs_persistence")
    g.append({"gate": "beats_persistence_baseline", "passed": skill is not None and skill > GATES[
        "min_brier_skill_vs_persistence"], "detail": f"Brier skill vs persistence = {skill:.3f}" if skill is not None
        else "not computable"})
    skill_us = bt.get("brier_skill_vs_uniform_swing")
    g.append({"gate": "competitive_with_uniform_swing", "passed": skill_us is not None and skill_us >= 0,
              "detail": f"Brier skill vs uniform-swing baseline = {skill_us:.3f}; a model that does not match the "
                        "simpler baseline is not published" if skill_us is not None else "not computable"})
    ece = bt["calibration"]["ece"]
    g.append({"gate": "calibration", "passed": ece is not None and ece <= GATES["max_ece"],
              "detail": f"ECE = {ece}" if ece is not None else "not computable"})
    cov = bt["pooled"]["model"]["coverage_80"]
    lo, hi = GATES["coverage_80_range"]
    g.append({"gate": "interval_coverage", "passed": cov is not None and lo <= cov <= hi,
              "detail": f"80% interval coverage = {cov:.3f} (target {lo}–{hi})" if cov is not None else "n/a"})
    hits = [c["seats_a_p10_p90"][0] <= c["seats_a_actual"] <= c["seats_a_p10_p90"][1] for c in bt["cycles"]]
    rate = sum(hits) / len(hits) if hits else None
    g.append({"gate": "seat_interval_coverage", "passed": rate is not None and rate >= GATES[
        "min_seat_interval_hit_rate"], "detail": f"actual seats inside the 80% seat interval in {sum(hits)}/{len(hits)} "
        "held-out cycles" if hits else "n/a"})
    with_prior = sum(r.prev_margin is not None for r in target_rows)
    share = with_prior / len(target_rows) if target_rows else 0.0
    g.append({"gate": "prior_result_coverage", "passed": share >= GATES["min_prior_coverage"],
              "detail": f"{with_prior}/{len(target_rows)} contests have a boundary-compatible prior result"})
    g.append({"gate": "polling_inputs", "passed": n_polls >= GATES["min_polls"],
              "detail": f"{n_polls} eligible national polls before cutoff (need ≥ {GATES['min_polls']})"})
    real_required = not get_settings().allows_synthetic_data
    g.append({"gate": "real_data", "passed": not (synthetic and real_required),
              "detail": "SYNTHETIC data — demo only" if synthetic else "official/registered sources"})
    return g


def run_forecast(db: Session, *, country: str, office_key: str, cycle_year: int, data_cutoff: date | None,
                 created_by: str, scenario: dict | None = None, seed: int = 20261014) -> ForecastRun:
    cycles = _office_cycles(db, country, office_key)
    target_date = next((d for y, d in cycles if y == cycle_year), None)
    mv = db.scalar(select(ModelVersion).where(ModelVersion.kind == "forecast", ModelVersion.version == M.MODEL_VERSION))
    if mv is None:
        mv = ModelVersion(kind="forecast", version=M.MODEL_VERSION, description="District OLS + Student-t national error",
                          params={"lead_days": M.LEAD_DAYS, "min_train_cycles": M.MIN_TRAIN_CYCLES, "gates": GATES})
        db.add(mv)
        db.flush()
    today = datetime.now(UTC).date()
    if data_cutoff and data_cutoff > today:
        raise ValueError("data cutoff cannot be in the future")
    cutoff = data_cutoff or (min(today, M.cutoff_for(target_date)) if target_date else today)
    run = ForecastRun(country_code=country, office_key=office_key, cycle_key=str(cycle_year), model_version_id=mv.id,
                      kind="scenario" if scenario else "forecast", scenario=scenario,
                      data_cutoff=datetime.combine(cutoff, datetime.min.time(), UTC), status="draft",
                      assumptions=ASSUMPTIONS, random_seed=seed, created_by=created_by)
    if target_date is None:
        run.status = "blocked"
        run.gate_results = [{"gate": "contests_known", "passed": False,
                             "detail": f"No {office_key} general-election contests for {country} {cycle_year} are "
                                       "loaded from a registered source."}]
        db.add(run)
        db.flush()
        return run
    if cutoff >= target_date:
        raise ValueError("data cutoff must precede election day")
    bt = backtest(db, country, office_key, before_year=cycle_year)
    train = _training(db, country, office_key, cycles, cycle_year, cutoff)
    target = cycle_inputs(db, country=country, office_key=office_key, year=cycle_year, cutoff=cutoff)
    if scenario and "national_environment_shift" in scenario:
        shift = float(scenario["national_environment_shift"])
        if abs(shift) > 0.3:
            raise ValueError("scenario shift must be within ±0.30")
        target.env_poll = (target.env_poll or target.env_prev_actual or 0.0) + shift
    synthetic = any(r.synthetic for r in target.rows)
    run.uses_synthetic_data = synthetic
    run.backtest = _jsonable(bt)
    run.inputs_summary = {"contests": len(target.rows), "env_poll": target.env_poll, "polls_used": target.n_polls,
                          "env_prev_actual": target.env_prev_actual, "train_cycles": [t.year for t in train],
                          "contests_without_prior": sum(r.prev_margin is None for r in target.rows)}
    gates = evaluate_gates(bt, target.rows, target.n_polls, synthetic)
    try:
        fitted = M.fit(train)
    except ValueError as exc:
        gates.append({"gate": "model_fit", "passed": False, "detail": str(exc)})
        fitted = None
    if fitted is not None:
        preds = M.predict(fitted, target)
        office = db.scalar(select(Office).where(Office.country_code == country, Office.key == office_key))
        sim = M.simulate(fitted, preds, target, office.total_seats if office else None, seed)
        run.contest_outputs = [{**asdict(p), "p_a": round(p.p_a, 4),
                                "interval_80": [round(p.mean - 1.2816 * p.sd, 4), round(p.mean + 1.2816 * p.sd, 4)]}
                               for p in preds]
        run.aggregate_outputs = {**sim, "party_a": _party_label(country, 0), "party_b": _party_label(country, 1),
                                 "coefficients": dict(zip(["intercept", "prev_margin", "incumbency", "swing"],
                                                          [round(float(c), 4) for c in fitted.coef], strict=True)),
                                 "sigma_national": round(fitted.sigma_national, 4),
                                 "sigma_district": round(fitted.sigma_district, 4)}
    run.gate_results = gates
    run.status = "validated" if all(g["passed"] for g in gates) else "blocked"
    db.add(run)
    db.flush()
    return run


def publish(db: Session, run: ForecastRun) -> ForecastRun:
    if run.kind != "forecast":
        raise PermissionError("scenarios cannot be published as forecasts")
    if run.status != "validated":
        raise PermissionError("only runs that passed every publication gate can be published")
    db.execute(select(ForecastRun).where(ForecastRun.country_code == run.country_code,
                                         ForecastRun.office_key == run.office_key,
                                         ForecastRun.cycle_key == run.cycle_key,
                                         ForecastRun.status == "published").with_for_update())
    for prev in db.scalars(select(ForecastRun).where(ForecastRun.country_code == run.country_code,
                                                     ForecastRun.office_key == run.office_key,
                                                     ForecastRun.cycle_key == run.cycle_key,
                                                     ForecastRun.status == "published")):
        prev.status = "withdrawn"
    run.status, run.published_at = "published", datetime.now(UTC)
    return run


def _party_label(country: str, i: int) -> str:
    from .data import MAJOR_PARTIES  # noqa: PLC0415

    return MAJOR_PARTIES[country][i]


def _jsonable(o):  # type: ignore[no-untyped-def]
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, uuid.UUID):
        return str(o)
    return o
