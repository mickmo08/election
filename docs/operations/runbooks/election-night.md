# Election night

T-7 days: load test staging at election-night workload; confirm each state results mapping against a past
certified canvass; confirm authorized race-call sources and editorial criteria; freeze deploys after T-48 h.
T-24 h: scale API to ≥ 6 tasks and workers to ≥ 4; verify alarms route to on-call; dry-run ingestion against
publisher test feeds where available.
Polls closing: respect per-state embargo (publication rules); monitor freshness (≤ 5 min target), quarantine,
dead letters; results desk reviews `count_decreased` and `status_regression` items immediately.
Calls: only via `POST /api/v1/admin/contests/{id}/race-calls` with the editorial basis noted.
Rollback plan: previous image tag noted in the incident channel before freeze.
