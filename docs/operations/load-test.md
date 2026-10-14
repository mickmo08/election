# Load testing

* Tool: `ops/loadtest/loadtest.py` (async httpx, closed loop). Workload mix and rationale are in its docstring:
  45% explorer list, 20% contest detail, 10% overview, 10% polling average (+trend), 5% issues, 5% map,
  5% assistant (offline provider).
* Run: `python ops/loadtest/loadtest.py --base <url> --users N --duration S --out result.json` with a dev or
  staging environment whose rate limits are raised for the test (the WAF/token buckets otherwise throttle a
  single client IP by design).
* Results: `docs/evidence/loadtest-20u-60s.json`, `docs/evidence/loadtest-50u-60s.json`; summary in `slos.md`.
* Findings fixed during load testing: assistant district resolution built full contest details per cycle
  (0.34 s → 0.125 s single query); the polling trend re-queried polls 9× (now one fetch).
* Remaining before launch: run against staging (ECS, RDS) at the election-night workload (2,000 users), add
  read caching for public reference endpoints if p95 is not met, and soak test the worker at 5-minute ingestion
  cadence.
