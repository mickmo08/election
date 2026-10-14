# External blockers and remaining verification

## External blockers (need people, decisions, credentials or approval)
| # | Blocker | Impact | Needed from | Remediation path |
|---|---|---|---|---|
| B1 | Build-environment egress blocks FEC, Census, Harvard Dataverse, MIT (HTTP 403 at proxy, verified 2026-10-14) | No real U.S. data could be ingested or verified here; all U.S. views show "unavailable" | Environment owner | Allow-list hosts in the deployment's egress policy, or upload files via Sources → Upload |
| B2 | No OpenFEC (api.data.gov) key | U.S. 2026 candidate filings not loaded | Data owner | Request key; store as secret; activate source |
| B3 | No state results feed mappings or licensed results/race-call feed | No 2026 results monitoring for the U.S. | Results desk + business | Configure per-state mappings; decide on a licensed feed |
| B4 | 2026 district plans after mid-decade redistricting not loaded | U.S. historical comparisons and forecasts disabled | Geo data owner | Add state redistricting sources + crosswalks |
| B5 | No licensed news/discussion source permitting text analysis | U.S. issue analysis unavailable | Business/legal | Contract a provider with TDM rights |
| B6 | No AWS deployment (cost approval + credentials not provided for this work) | Staging/prod not deployed; SLOs unmeasured in cloud; RDS PITR drill not run | Budget owner | Approve costs; provide account + state backend; run Terraform + Deploy workflow |
| B7 | No OIDC identity provider configured | SSO not exercised against a real IdP (tested with RS256 + mock JWKS) | IT / customer | Register application; set issuer/audience/JWKS |
| B8 | No LLM provider key | Assistant runs on the deterministic offline composer; LLM path tested only with a mocked client | Budget owner | Provide key; run assistant eval with the live provider |
| B9 | No billing provider decision | Billing not integrated (entitlements/metering are) | Product/finance | Choose provider; integrate |
| B10 | Legal review | See `legal-review-questions.md` | Counsel | — |
| B11 | Editorial race-call criteria | Calls can be recorded but criteria are not defined | Editorial leadership | Approve policy before election night |

## Remaining verification (engineering)
* Run CI on GitHub (workflows written; Actions not executed from this environment).
* Docker images not built here (no Docker daemon); Dockerfiles untested until CI `images` job runs.
* Cloud load test at election-night workload; per-task capacity; p95 target currently missed in sandbox.
* RDS point-in-time and cross-region restore drills.
* Forecast evaluation on real historical U.S. cycles (2012–2024) once B1/B4 are resolved; current model is
  blocked on synthetic data and has not been validated on real elections.
* Human-labelled issue-classification set (current labels are synthetic generator truth).
* Manual accessibility audit (screen reader, keyboard-only) beyond automated axe checks.
* Verify U.S. electoral-system rules marked `unverified_reference` against current statutes.
* Secret-rotation automation for DB role passwords; S3 cross-region replication decision.
* SBOM generation and image signing.
