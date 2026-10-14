# Forecast evaluation: XS xs_assembly 2026

Status: **blocked** · data cutoff 2026-10-14T00:00:00+00:00 · synthetic data: True

## Publication gates

- PASS `backtest_cycles` — 4 held-out cycles (need ≥ 3)
- PASS `beats_persistence_baseline` — Brier skill vs persistence = 0.170
- FAIL `competitive_with_uniform_swing` — Brier skill vs uniform-swing baseline = -0.025; a model that does not match the simpler baseline is not published
- PASS `calibration` — ECE = 0.0697
- PASS `interval_coverage` — 80% interval coverage = 0.800 (target 0.7–0.92)
- PASS `seat_interval_coverage` — actual seats inside the 80% seat interval in 3/4 held-out cycles
- PASS `prior_result_coverage` — 40/40 contests have a boundary-compatible prior result
- PASS `polling_inputs` — 5 eligible national polls before cutoff (need ≥ 3)
- PASS `real_data` — SYNTHETIC data — demo only

## Backtest (Expanding-window, time-respecting backtest; cutoff = election day − 14 days)

| Held-out cycle | Trained on | Brier model | Brier uniform swing | Brier persistence | Log loss model | MAE margin | 80% coverage | Seats pred. median (80%) | Seats actual |
|---|---|---|---|---|---|---|---|---|---|
| 2018 | 2012, 2014, 2016 | 0.059 | 0.063 | 0.084 | 0.194 | 0.030 | 0.85 | 13 (10–16) | 14 |
| 2020 | 2012, 2014, 2016, 2018 | 0.090 | 0.083 | 0.123 | 0.255 | 0.047 | 0.70 | 17 (15–20) | 20 |
| 2022 | 2012, 2014, 2016, 2018, 2020 | 0.074 | 0.069 | 0.106 | 0.242 | 0.040 | 0.85 | 22 (20–25) | 25 |
| 2024 | 2012, 2014, 2016, 2018, 2020, 2022 | 0.094 | 0.094 | 0.070 | 0.280 | 0.034 | 0.80 | 23 (20–25) | 27 |

## Pooled

| Method | Brier | Log loss | MAE margin | 80% coverage | n |
|---|---|---|---|---|---|
| model | 0.079 | 0.243 | 0.038 | 0.80 | 160 |
| persistence | 0.095 | 0.290 | 0.052 | 0.74 | 160 |
| uniform_swing | 0.077 | 0.236 | 0.039 | 0.84 | 160 |

Brier skill vs persistence: 0.170; vs uniform swing: -0.025.

## Calibration (pooled)

| Bin | n | Mean predicted | Observed |
|---|---|---|---|
| 0.0-0.1 | 58 | 0.022 | 0.069 |
| 0.1-0.2 | 9 | 0.159 | 0.333 |
| 0.2-0.3 | 6 | 0.256 | 0.333 |
| 0.3-0.4 | 7 | 0.353 | 0.286 |
| 0.4-0.5 | 8 | 0.438 | 0.625 |
| 0.5-0.6 | 6 | 0.556 | 0.833 |
| 0.6-0.7 | 4 | 0.631 | 0.75 |
| 0.7-0.8 | 1 | 0.771 | 1.0 |
| 0.8-0.9 | 9 | 0.873 | 1.0 |
| 0.9-1.0 | 52 | 0.983 | 1.0 |

Expected calibration error: 0.0697
