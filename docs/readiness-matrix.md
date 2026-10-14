# Production readiness matrix

Legend: **Met** = implemented and verified with the cited evidence · **Met (sandbox)** = verified locally/CI-style,
not yet in a cloud environment · **Partial** = implemented with stated gaps · **Blocked** = depends on an external
item in `blockers.md` · **Not met**.

Overall verdict: **not production-ready.** The platform software, controls and evidence are in place for a
staging deployment; launch for the U.S. 2026 midterms is blocked on real data access (B1–B5), cloud deployment
(B6), identity provider (B7), and measured SLOs.

## Product capabilities
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1.1 | Overview / contest / district explorer with comparisons | Met (sandbox) | `frontend/src/app/{page,explorer,contests}`; e2e `explorer -> contest detail` |
| 1.2 | Versioned district maps; boundary compatibility checks | Met (sandbox) | `services/results.compatibility`; `test_boundary_compatibility`; `docs/methodology/historical-comparison.md` |
| 1.3 | Accessible charts/maps with table alternatives; downloadable datasets | Met (sandbox) | `components/Charts.tsx`, `DistrictMap.tsx`; axe WCAG 2 A/AA checks in all e2e tests; CSV export test |
| 1.4 | Source attribution, freshness, definitions, limitations on every view | Met (sandbox) | `AboutData` on analytical views; freshness badges |
| 2.1 | Source registry (owner, terms, refresh, licence, coverage, reliability) | Met | `docs/data/source-register.md` (generated); `/sources` |
| 2.2 | Real access methods, no invented APIs | Partial / Blocked | Endpoint patterns documented with verification notes; not callable from build env (B1, B2) |
| 2.3 | Immutable raw files + provenance + lineage | Met | `raw_files` append-only trigger; S3 Object Lock in IaC; `test_raw_files_are_immutable`, provenance asserts |
| 2.4 | Validation (schema, totals, joins, duplicates, identity) + quarantine + review tools | Met (sandbox) | `test_ingestion.py`; admin quarantine UI/API |
| 2.5 | Idempotent, retryable, observable jobs; DLQ | Met (sandbox) | `test_queue.py`; metrics + alarms |
| 2.6 | Corrections and historical snapshots | Met | `test_official_results_status_lifecycle`, `test_corrected_and_recount_history_preserved` |
| 3.x | Results statuses, completeness only when supported, no LLM calls, authorized calls only, disputes | Met (sandbox) / Blocked for U.S. live data | results tests; editorial policy doc; B3 |
| 4.x | Issue analysis: licensed text, multilingual, dedup, frequency≠opinion, coverage, human review, model versions, aggregation | Partial | Implemented and tested; classifier evaluated only on synthetic labels; en/es topics only; U.S. source blocked (B5) |
| 5.x | Polling metadata, populations, overlap handling, design-appropriate uncertainty, consent-based surveys, suppression | Met (sandbox) | `test_domain.py`, survey tests, `docs/methodology/polling.md` |
| 6.1 | Documented method, baselines, time-respecting validation, leakage prevention | Met (sandbox) | `test_forecast.py` (perturbation + cutoff tests); `docs/methodology/forecasting.md` |
| 6.2 | Calibration, scoring vs baselines, dependence, redistricting, gates disable publication | Met (sandbox) | `docs/evidence/forecast-eval-xs-2026.md` — run correctly **blocked** |
| 6.3 | Validated forecast for U.S. 2026 | **Blocked / Not met** | No real data (B1, B4); model not validated on real elections |
| 7.1 | Assistant: read-only tools, backend numbers, citations, tenant permissions, injection resistance, missing/stale evidence | Met (sandbox, offline provider) | `docs/evidence/assistant-eval.json` (all 8 metrics pass); `test_assistant.py` |
| 7.2 | Provider independence, fallback, budgets, reproducible records | Partial | Anthropic (SDK) + OpenAI-compatible + offline; live LLM not evaluated (B8) |
| 8.x | Reports with references/method/freshness/uncertainty/reproducibility; review; versioned publication; corrections; AI label | Met (sandbox) | `test_reports.py`; e2e editorial workflow |
| 9.1 | Tenant isolation enforced in server and database | Met | `test_security.py` (API + raw SQL RLS); `docs/security/tenant-isolation.md` |
| 9.2 | Roles; OIDC; enterprise SSO | Met (sandbox) / Blocked for real IdP | RBAC matrix tests; RS256/JWKS tests; staging-mode run with mock IdP (B7) |
| 9.3 | Audit trails for access, changes, imports, exports, publication | Met | append-only `audit_events`; tests assert publish/export events |
| 9.4 | Encryption, secrets, retention, deletion, export controls | Partial | KMS/TLS/Secrets Manager in IaC (not applied); retention + purge implemented, purge not exercised in tests |
| 9.5 | Regional publication restrictions | Met (sandbox) | country `publication_rules` + tenant restrictions enforced at publish |
| 9.6 | Legal/licensing questions documented | Met | `docs/legal-review-questions.md` |
| 10.x | Org management, entitlements, metering, quotas; billing only with provider | Met (sandbox) / billing Blocked | usage/quota tests; billing shows `not_configured` (B9) |

## Production engineering
| Criterion | Status | Evidence |
|---|---|---|
| Migrations + rollback/recovery | Met (sandbox) | upgrade→downgrade→upgrade round trip; non-superuser owner migration on staging-mode cluster; expand/contract policy |
| CI checks, reproducible builds | Partial | `.github/workflows/ci.yml` (lint, tests, migrations, audits, e2e, gitleaks, checkov, terraform, image builds) — **not yet executed on GitHub**; pinned deps + lockfile |
| Unit/integration/e2e tests for critical workflows | Met (sandbox) | 92 backend tests; 6 Playwright e2e with axe (`docs/evidence/`) |
| Authorization and cross-tenant tests | Met | `test_security.py` |
| Dependency + secret scanning | Met (local) | pip-audit, npm audit: 0 known vulns; detect-secrets baseline; gitleaks config |
| Structured logs, metrics, tracing, alerts | Partial | JSON logs with request/tenant ids; Prometheus metrics; CloudWatch alarms in IaC; distributed tracing not implemented (single service hop; request ids propagate) |
| Freshness + data-quality monitoring | Met (sandbox) | freshness evaluation, breach log + alarm, quarantine gauge |
| Queue recovery + dead letters | Met (sandbox) | lease recovery + DLQ tests; runbook |
| Backups with tested restore | Met (sandbox) / RDS drill Not met | `docs/operations/backup-restore.md`; restore verify output; tamper test |
| Rate limits, upload protections, abuse controls | Met (sandbox) | tests; WAF in IaC |
| Staging and production configuration | Met (sandbox) | config guards; `envs/*.tfvars`; `docs/evidence/staging-mode-verify.txt` (9/9) |
| Infrastructure as code | Met (static) | `terraform validate` OK; checkov 212/0 with documented exceptions; never applied (B6) |
| Health checks, deployment rollback, runbooks | Met (design) | `/healthz`, `/readyz`; ECS circuit breaker; `docs/operations/runbooks/` (9 runbooks) |
| Load tests against documented workload | Met (sandbox) | `docs/operations/load-test.md`; results JSON |
| Measured availability/latency/freshness/recovery targets | **Not met** | Targets proposed in `slos.md`; only sandbox latency measured (p95 941 ms @ 20 users — misses 800 ms target) |
| Synthetic data isolated and labelled; missing integrations visibly unavailable | Met | fictional XS country; production refusal; banners; e2e "unavailable" test |
