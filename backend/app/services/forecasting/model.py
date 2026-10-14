"""District-level two-party forecast with correlated national error, baselines and backtests.

See docs/methodology/forecasting.md for the specification, assumptions and limitations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .data import ContestRow, CycleInputs

MODEL_VERSION = "district-ols-tnat-1.0.0"
LEAD_DAYS = 14  # forecasts and backtests use a cutoff this many days before election day
MIN_TRAIN_CYCLES = 3
FALLBACK_INFLATION = 1.5  # error multiplier when no comparable prior result exists


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


@dataclass
class Fitted:
    coef: np.ndarray  # intercept, prev_margin, incumbency, swing
    sigma_national: float
    sigma_district: float
    n_train: int
    train_cycles: list[int]
    fallback_mean: float  # mean margin used when no prior exists


@dataclass
class Prediction:
    contest_id: str
    district_code: str
    mean: float
    sd: float
    p_a: float
    flags: list[str] = field(default_factory=list)


def features(row: ContestRow, env_poll: float | None, env_prev: float | None) -> np.ndarray | None:
    if row.prev_margin is None:
        return None
    swing = (env_poll - env_prev) if (env_poll is not None and env_prev is not None) else 0.0
    return np.array([1.0, row.prev_margin, float(row.incumbency), swing])


def _design(train: list[CycleInputs]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X, y, cyc = [], [], []
    for ci in train:
        for r in ci.rows:
            f = features(r, ci.env_poll, ci.env_prev_actual)
            if f is None or r.margin is None or not (r.has_a and r.has_b):
                continue
            X.append(f)
            y.append(r.margin)
            cyc.append(ci.year)
    return np.array(X), np.array(y), np.array(cyc)


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    lam = np.diag([0.0, 1e-3, 1e-3, 1e-3])  # tiny ridge for stability; intercept unpenalised
    return np.linalg.solve(X.T @ X + lam, X.T @ y)


def fit(train: list[CycleInputs]) -> Fitted:
    Xa, ya, ca = _design(train)
    cycles = sorted(set(ca.tolist()))
    if len(cycles) < MIN_TRAIN_CYCLES:
        raise ValueError(f"need >= {MIN_TRAIN_CYCLES} training cycles with comparable data, have {len(cycles)}")
    coef = _ols(Xa, ya)
    # Error scales from leave-one-cycle-out residuals: in-sample residuals understate the national
    # error because the swing coefficient is fitted on the same few cycles.
    cycle_means, within = [], []
    for c in cycles:
        held = ca == c
        r = ya[held] - Xa[held] @ _ols(Xa[~held], ya[~held])
        cycle_means.append(r.mean())
        within.append(r - r.mean())
    sigma_n = max(0.015, float(np.sqrt(np.mean(np.square(cycle_means)))))
    sigma_d = max(0.02, float(np.concatenate(within).std(ddof=1)))
    return Fitted(coef, sigma_n, sigma_d, len(ya), cycles, float(np.mean(ya)))


def predict(model: Fitted, ci: CycleInputs) -> list[Prediction]:
    preds = []
    for r in ci.rows:
        flags = []
        f = features(r, ci.env_poll, ci.env_prev_actual)
        sd_d = model.sigma_district
        if f is None:
            mean = model.fallback_mean + ((ci.env_poll - ci.env_prev_actual) if ci.env_poll is not None and
                                          ci.env_prev_actual is not None else 0.0)
            sd_d *= FALLBACK_INFLATION
            flags.append("no_comparable_prior_result")
        else:
            mean = float(f @ model.coef)
            if r.prev_basis == "crosswalk":
                sd_d *= 1 + (1 - r.prev_overlap)
                flags.append(f"prior_via_crosswalk_{r.prev_overlap:.0%}")
        if ci.env_poll is None:
            flags.append("no_polls_national_uncertainty_inflated")
        sd = math.sqrt(model.sigma_national ** 2 * (1.5 if ci.env_poll is None else 1.0) + sd_d ** 2)
        if not r.has_a and not r.has_b:
            p, flags = 0.5, [*flags, "no_major_party_candidates"]
        elif not r.has_b:
            p, flags = 1.0, [*flags, "uncontested_by_party_b"]
        elif not r.has_a:
            p, flags = 0.0, [*flags, "uncontested_by_party_a"]
        else:
            p = norm_cdf(mean / sd)
        preds.append(Prediction(str(r.contest_id), r.district_code, round(mean, 4), round(sd, 4), p, flags))
    return preds


def baseline_persistence(model: Fitted, ci: CycleInputs) -> list[Prediction]:
    """Previous margin carries over; spread from the model's residual scale (fair comparison)."""
    out = []
    for r in ci.rows:
        mean = r.prev_margin if r.prev_margin is not None else model.fallback_mean
        sd = math.sqrt(model.sigma_national ** 2 + model.sigma_district ** 2) * 1.25
        out.append(Prediction(str(r.contest_id), r.district_code, mean, sd, norm_cdf(mean / sd)))
    return out


def baseline_uniform_swing(model: Fitted, ci: CycleInputs) -> list[Prediction]:
    swing = (ci.env_poll - ci.env_prev_actual) if ci.env_poll is not None and ci.env_prev_actual is not None else 0.0
    out = []
    for r in ci.rows:
        mean = (r.prev_margin if r.prev_margin is not None else model.fallback_mean) + swing
        sd = math.sqrt(model.sigma_national ** 2 + model.sigma_district ** 2) * 1.1
        out.append(Prediction(str(r.contest_id), r.district_code, mean, sd, norm_cdf(mean / sd)))
    return out


def simulate(model: Fitted, preds: list[Prediction], ci: CycleInputs, total_seats: int | None, seed: int,
             n: int = 10000) -> dict:
    """Seat distribution with a shared national shock (Student-t, df = #training cycles)."""
    rng = np.random.default_rng(seed)
    df = max(3, len(model.train_cycles))
    nat_scale = model.sigma_national * (1.5 if ci.env_poll is None else 1.0)
    nat = rng.standard_t(df, size=n) * nat_scale * math.sqrt((df - 2) / df)
    means = np.array([p.mean for p in preds])
    sd_d = np.sqrt(np.maximum(np.array([p.sd for p in preds]) ** 2 - nat_scale ** 2, 1e-6))
    fixed = np.array([p.p_a in (0.0, 1.0) and "uncontested" in " ".join(p.flags) for p in preds])
    draws = means[None, :] + nat[:, None] + rng.standard_normal((n, len(preds))) * sd_d[None, :]
    wins = (draws > 0).astype(int)
    wins[:, fixed] = np.array([int(p.p_a == 1.0) for p in preds])[fixed]
    seats_a = wins.sum(axis=1)
    k = len(preds)
    majority = (total_seats // 2 + 1) if total_seats else (k // 2 + 1)
    hist = np.bincount(seats_a, minlength=k + 1)
    return {
        "n_simulations": n, "contests_modelled": k, "seats_total_office": total_seats, "majority_threshold": majority,
        "seats_a": {"mean": round(float(seats_a.mean()), 2), "median": int(np.median(seats_a)),
                    "p10": int(np.percentile(seats_a, 10)), "p90": int(np.percentile(seats_a, 90))},
        "p_a_majority": round(float((seats_a >= majority).mean()), 4) if total_seats is None or k == total_seats
        else None,
        "majority_note": None if total_seats is None or k == total_seats else
        f"Only {k} of {total_seats} seats are modelled; chamber control probability is not reported.",
        "distribution": [{"seats": i, "share": round(float(c) / n, 5)} for i, c in enumerate(hist) if c],
        "dependence": f"Shared national error ~ Student-t(df={df}, scale={nat_scale:.3f}); district errors independent.",
    }


# ------------------------------------------------------------------ evaluation metrics

def brier(preds: list[Prediction], outcomes: dict[str, float]) -> float | None:
    pairs = [(p.p_a, 1.0 if outcomes[p.contest_id] > 0 else 0.0) for p in preds if p.contest_id in outcomes]
    return float(np.mean([(p - o) ** 2 for p, o in pairs])) if pairs else None


def log_loss(preds: list[Prediction], outcomes: dict[str, float]) -> float | None:
    eps = 1e-4
    pairs = [(min(1 - eps, max(eps, p.p_a)), 1.0 if outcomes[p.contest_id] > 0 else 0.0)
             for p in preds if p.contest_id in outcomes]
    return float(-np.mean([o * math.log(p) + (1 - o) * math.log(1 - p) for p, o in pairs])) if pairs else None


def calibration(preds: list[Prediction], outcomes: dict[str, float], bins: int = 10) -> dict:
    rows = []
    ece, n_total = 0.0, 0
    pairs = [(p.p_a, 1.0 if outcomes[p.contest_id] > 0 else 0.0) for p in preds if p.contest_id in outcomes]
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, o) for p, o in pairs if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if not sel:
            continue
        mp, mo = float(np.mean([s[0] for s in sel])), float(np.mean([s[1] for s in sel]))
        rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(sel), "mean_predicted": round(mp, 3),
                     "observed_rate": round(mo, 3)})
        ece += len(sel) * abs(mp - mo)
        n_total += len(sel)
    return {"bins": rows, "ece": round(ece / n_total, 4) if n_total else None}


def interval_coverage(preds: list[Prediction], outcomes: dict[str, float], z: float = 1.2816) -> float | None:
    hits = [abs(outcomes[p.contest_id] - p.mean) <= z * p.sd for p in preds if p.contest_id in outcomes and
            not any("uncontested" in f for f in p.flags)]
    return float(np.mean(hits)) if hits else None


def mae(preds: list[Prediction], outcomes: dict[str, float]) -> float | None:
    e = [abs(outcomes[p.contest_id] - p.mean) for p in preds if p.contest_id in outcomes]
    return float(np.mean(e)) if e else None


def score(preds: list[Prediction], outcomes: dict[str, float]) -> dict:
    return {"brier": brier(preds, outcomes), "log_loss": log_loss(preds, outcomes), "mae_margin": mae(preds, outcomes),
            "coverage_80": interval_coverage(preds, outcomes), "n": sum(p.contest_id in outcomes for p in preds)}


def cutoff_for(election_date: date) -> date:
    return election_date - timedelta(days=LEAD_DAYS)
