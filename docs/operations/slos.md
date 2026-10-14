# Service level objectives (proposed — not yet measured in production)

| SLI | Proposed target | Measurement | Status |
|---|---|---|---|
| API availability | 99.9% monthly (99.95% during the 72 h around election night) | ALB non-5xx / total for `/api/*` | **Not measured** — no staging/production deployment yet |
| API latency | p95 < 800 ms, p99 < 2 s for read endpoints; assistant p95 < 10 s | ALB `TargetResponseTime` p95 | Sandbox only (below) |
| Results freshness (election night) | New official snapshot visible ≤ 5 min after the publisher posts it | `retrieved_at − source_as_of` per snapshot | **Not measured** — no live results feed connected |
| Source freshness | Each source within its SLA (e.g. FEC 48 h) | `source_staleness_hours` gauge / freshness breach alarm | Mechanism tested; no live sources |
| Ingestion correctness | 0 unreviewed error-level quarantine items older than 24 h | quarantine age | Mechanism in place |
| Recovery | RPO ≤ 5 min (RDS PITR); RTO ≤ 1 h for database restore | restore drill | Logical restore drill measured in sandbox (below); RDS PITR drill pending |

## Assumptions
Workload at launch (assumed; validate with product): ≤ 200 concurrent active users across tenants on normal days,
≤ 2,000 on election night, read-heavy (≈ 90% reads), assistant ≤ 5% of requests, results ingestion every
1–5 minutes for ≤ 60 sources on election night. Targets assume 3+ API tasks behind the ALB in two AZs and a
Multi-AZ RDS instance.

## Sandbox measurements (2026-10-14, NOT production evidence)
Environment: one 4-vCPU container running the load generator, 4 Uvicorn workers and PostgreSQL 16 together;
synthetic dataset; rate limits raised for the test. Workload: `ops/loadtest/loadtest.py` mix (closed loop, no think time).

| Users | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 20 | 3693 | 61.1 req/s | 47.9 ms | 941.3 ms | 1215.4 ms | 0 |
| 50 | 3536 | 58.1 req/s | 613.3 ms | 2698.2 ms | 4835.3 ms | 0 |

Interpretation: the sandbox saturates near 60 req/s (CPU-bound, shared with the generator and database); beyond
that, added users only add queueing latency, with no errors. The p95 target is **not met** at 20 users in this
environment (941 ms). Capacity per Fargate task must be measured on staging before targets can be claimed.
