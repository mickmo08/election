# Election Intelligence Platform

A multi-tenant election intelligence and public-opinion research platform for newsrooms, academic researchers,
civic organizations and election analysts: verified election data with provenance, results monitoring,
boundary-aware historical comparison, aggregate issue analysis, published polls and consent-based survey
aggregates, gated statistical forecasts, a source-backed AI research assistant, and an editorial report workflow.

> **Status: pre-production.** Software, tests and operational tooling are in place and verified locally. No real
> U.S. data is loaded yet (the build environment could not reach authoritative sources), nothing is deployed to the
> cloud, and service targets are not yet measured in production. See
> [`docs/readiness-matrix.md`](docs/readiness-matrix.md) and [`docs/blockers.md`](docs/blockers.md).
> Demo data is the fictional **Synthetic Federation (XS)**, clearly labelled and refused in production.

## Repository
| Path | Contents |
|---|---|
| `backend/` | FastAPI API, worker, ingestion framework + adapters, domain services, Alembic migrations, tests, evals |
| `frontend/` | Next.js (App Router, TypeScript) UI, Playwright + axe end-to-end tests |
| `infra/terraform/` | AWS infrastructure (VPC, RDS PostgreSQL 16, S3 Object Lock, ECS Fargate, ALB + WAF, alarms) |
| `ops/` | DB role bootstrap, deploy scripts, backup/restore verification, load generator, staging-mode tooling |
| `docs/` | Architecture, security, data, methodology, policies, operations, evidence |
| `.github/workflows/` | CI (lint, tests, migrations, audits, e2e, secret + IaC scanning, images) and Deploy |

## Quick start (local)
See [`docs/deployment.md`](docs/deployment.md). Short version: bootstrap roles, `alembic upgrade head`,
`python -m app.cli seed-demo`, start `uvicorn` + `python -m app.cli worker`, then `npm run build && npm start` in
`frontend/` and use the demo sign-in at http://localhost:3000.

## Documentation map
* Architecture & decisions: [`docs/architecture.md`](docs/architecture.md), [`docs/decisions-log.md`](docs/decisions-log.md)
* Security & privacy: [`docs/security/`](docs/security/) (threat model, tenant isolation, research scope, IaC exceptions)
* Data: [`docs/data/source-register.md`](docs/data/source-register.md), identity resolution
* Adapters: [`docs/adapters/country-adapter-contract.md`](docs/adapters/country-adapter-contract.md), normalized formats
* Methodology: forecasting, polling, issue analysis, historical comparison ([`docs/methodology/`](docs/methodology/))
* Policies: editorial race calls, assistant scope ([`docs/policies/`](docs/policies/))
* Operations: SLOs, load test, backup/restore, abuse controls, billing, runbooks ([`docs/operations/`](docs/operations/))
* Evidence: test reports, evaluations, load tests, restore and staging-mode verification ([`docs/evidence/`](docs/evidence/))
* Legal questions for qualified review: [`docs/legal-review-questions.md`](docs/legal-review-questions.md)
