# Forecasting methodology (model `district-ols-tnat-1.0.0`)

Forecasts are statistical estimates from documented methods, never LLM output, and never certainties.

## Inputs (as knowable at the data cutoff)
* Last general-election result in a **boundary-compatible** district (identical plan or crosswalk ≥ coverage),
  as the two-party margin m = (A − B)/(A + B) between the country's two largest parties.
* Incumbency (+1 party A, −1 party B, 0 open) from candidacies.
* National environment: recency/size-weighted two-party margin of generic-ballot polls whose fieldwork ended
  ≥ 1 day before the cutoff; overlapping tracking releases de-duplicated.
* Cutoff default: min(today, election day − 14 days). Future cutoffs are rejected.

## Model
`margin_d = β0 + β1·prior_margin_d + β2·incumbency_d + β3·(poll_env_t − prior_national_margin) + ε`
fitted by (lightly ridge-stabilised) least squares on earlier cycles only.
Uncertainty: ε = national shock (Student-t, df = number of training cycles) + district error. Both scales are
estimated from **leave-one-cycle-out** residuals (in-sample residuals understated national error — found and
fixed during evaluation). Districts without a comparable prior use the mean prior plus swing and 1.5× district
error; crosswalk priors inflate error by (2 − overlap). 10,000 simulations give seat distributions; contests
move together through the shared shock (dependence). Chamber-control probability is reported only when every
seat is modelled.

## Baselines
Persistence (prior margin) and uniform national swing, scored with the same uncertainty scale.

## Validation (time-respecting)
Expanding window: for each held-out cycle t, train only on cycles < t, build inputs at t's cutoff, score against
t's final results. Leakage guards: outcomes after the cutoff are structurally hidden (`cycle_inputs` asserts),
all prior results/polls used are logged with dates and tested to precede the cutoff, and a perturbation test
proves changing t's results cannot change t's predictions (`tests/test_forecast.py`).
Metrics: Brier score, log loss, margin MAE, 80% interval coverage, calibration bins + ECE, seat-interval hits,
Brier skill vs both baselines.

## Publication gates (all must pass)
≥ 3 held-out cycles · Brier skill > 0 vs persistence · Brier skill ≥ 0 vs uniform swing · ECE ≤ 0.08 ·
80% coverage in [0.70, 0.92] · actual seats inside 80% seat interval in ≥ 60% of held-out cycles ·
≥ 80% of contests with a compatible prior · ≥ 3 eligible polls · no synthetic data in production.
Failing runs are `blocked`; outputs are withheld from tenants; only operators can publish `validated` runs.
Scenarios (e.g. "+3 points national swing") are labelled `scenario` and can never be published as forecasts.

## Current evaluation (synthetic data only)
See `docs/evidence/forecast-eval-xs-2026.md`. Model Brier 0.079 vs persistence 0.095 (skill +0.17) and uniform
swing 0.077 (skill −0.025) over 160 held-out contests; ECE 0.070; 80% coverage 0.80; seat interval hit 3/4.
**Status: blocked** — it does not beat uniform swing, and calibration bins show party A under-predicted in the
middle range. On synthetic data generated close to uniform swing this is expected; it is not evidence about
real elections.

## U.S. 2026 status
Unavailable. No verified historical returns, boundaries or contest lists are loaded (sources blocked or not yet
credentialed), so the run is blocked at `contests_known`. Additional U.S.-specific work before publication:
state-level primaries/runoffs, top-two/RCV states (Alaska, Maine), Louisiana's system change, mid-decade
redistricting crosswalks, House–Senate–governor correlation, and evaluation on 2012–2024 real cycles.

## Limitations
Two-party framing (multi-party systems need a different model family); historical results may include
post-cutoff corrections; generic-ballot polls are a coarse national signal; small numbers of training cycles make
national-error estimates uncertain (mitigated by Student-t tails and the seat-interval gate).
