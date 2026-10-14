# Architecture

## Context
A multi-tenant research platform for newsrooms, researchers and civic organizations. It ingests verified
election data from registered sources, explains results and geography, analyzes aggregate issue coverage and
published polls/surveys, produces gated statistical forecasts, and offers a tool-using research assistant.

```
            Browser (Next.js app, same-origin)                 Identity provider (OIDC, enterprise SSO)
                     │  /api/* proxied                                   │ JWKS
                     ▼                                                   ▼
   ┌──────────── ALB + WAF (TLS, rate rule) ──────────────┐     FastAPI API (election_app role, RLS)
   │  /       → web (Next.js standalone)                  │───▶ • authN (OIDC JWT) / authZ (roles)
   │  /api/*  → api (FastAPI)                             │     • read APIs, editorial workflows
   └──────────────────────────────────────────────────────┘     • enqueues jobs only
                                                                     │
          EventBridge (5 min) → scheduler task ──enqueue──▶  PostgreSQL 16 (RDS)  ◀── worker (election_worker, BYPASSRLS)
                                                             • relational + JSONB      • ingestion adapters
                                                             • RLS tenant isolation    • forecasting runs
                                                             • jobs table (queue+DLQ)  • classification, retention
                                                                     │
                                                         S3 raw store (versioned, Object Lock, KMS)
```

## Components
| Component | Responsibility | Code |
|---|---|---|
| API | Authentication, RBAC, read/query APIs, editorial workflows, uploads (stored, then queued) | `backend/app/api`, `auth.py` |
| Worker | Durable job execution: ingestion, uploads, forecasts, classification, freshness, retention | `queue.py`, `jobs.py`, `cli.py worker` |
| Scheduler | Enqueues due jobs with idempotency keys (one per source per hour) | `jobs.schedule_due` |
| Ingestion framework | fetch → immutable raw store → parse → validate → quarantine → transactional load | `ingestion/framework.py` |
| Country adapters | Per-country structure, rules, sources (US, fictional XS) | `countries/` |
| Source adapters | Publisher formats → normalized loads | `ingestion/adapters/` |
| Domain services | Results, polling, surveys, issues, forecasting, assistant, reports | `services/` |
| Web | Accessible UI for all views; charts/maps with table alternatives | `frontend/` |

## Data model (global, not U.S.-specific)
`countries → admin_levels/admin_units (hierarchy, validity periods) → offices (+ electoral systems) →
district_plans (versioned boundaries, boundary_status, same_boundaries_as) → districts (GeoJSON; PostGIS
geometry when available) → district_crosswalks`. Elections: `election_cycles → elections (kind: general,
primary, runoff, special…; date + legal basis) → contests (office, district or unit, seats/magnitude,
electoral system, partisan primary party, seat class) → candidacies (candidate, party, status)`.
Parties carry aliases and successor links; coalitions have dated membership. Results are append-only
`result_snapshots` (status, source timestamps, reporting completeness only when supported, supersedes link)
with `result_lines`; `race_calls` come only from authorized sources. Provenance: `sources → raw_files
(sha256, URL, publisher, retrieval time, schema version) → ingestion_runs (adapter version, params, checks)
→ quarantine_items`; derived rows carry `source_id` and `ingestion_run_id`.

Tenant-owned tables (RLS): reports, report_versions, survey_datasets, survey_responses, assistant_queries,
usage_events, exports, audit_events; `polls` and `documents` allow `tenant_id NULL` for platform-wide rows.

## Key flows
1. **Ingestion**: scheduler → job → adapter.fetch (or uploaded file) → raw store (write-once) → idempotency
   check → savepoint → parse/validate/load → quarantine items → run status (`succeeded|partial|quarantined|failed`).
2. **Results monitoring**: each publication = new snapshot; corrections/recounts reference what they supersede;
   certified totals can change only via `corrected`/`recount` (otherwise quarantined).
3. **Forecast**: operator enqueues → worker builds leakage-safe inputs at the cutoff → backtest → gates →
   `validated|blocked` → operator may publish only a `validated` forecast.
4. **Assistant**: policy check → LLM tool loop (or deterministic planner) over read-only RLS-scoped tools →
   grounding check → fallback → persisted query record (provider, model, prompt version, tools, citations).
5. **Reports**: draft → submit → review (different person) → publish (blocked by publication rules) →
   corrections as new versions; published versions immutable in the database.

## Decisions (ADR summary)
| # | Decision | Rationale | Revisit when |
|---|---|---|---|
| 1 | FastAPI + SQLAlchemy + Alembic; Next.js + TypeScript | Mature, typed, fits analytics workloads | — |
| 2 | PostgreSQL job queue (`SKIP LOCKED`, retries, dead-letter state) instead of SQS/Redis | One stateful service to operate; transactional enqueue with data writes; volume is low (≤ thousands of jobs/day) | Sustained > ~50 jobs/s or fan-out needs |
| 3 | Tenant isolation via Postgres RLS + separate DB roles (app subject to RLS; worker BYPASSRLS; backup BYPASSRLS read-only) | Isolation enforced below application code; tested with raw SQL | — |
| 4 | GeoJSON in JSONB + optional PostGIS generated column | Works without PostGIS (dev/CI), uses spatial index where available (RDS) | Spatial queries become central |
| 5 | Demo data is a fictional country (XS) through the real pipeline | Synthetic rows can never be joined to or mistaken for real data; refused in production | — |
| 6 | Forecast = documented two-party district model with correlated national error, strict gates | Reproducible, testable; publication blocked unless it beats baselines and is calibrated | Multi-party countries need a different model family |
| 7 | Assistant computes nothing itself; deterministic composer fallback | Numbers come from backend code; grounding check rejects unsupported numbers | — |
| 8 | AWS (ECS Fargate, RDS, S3, WAF) via Terraform | Managed services, single cloud as requested | — |
