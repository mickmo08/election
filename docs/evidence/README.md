# Evidence index (captured 2026-10-14 in the build sandbox — not cloud/production evidence)

| Evidence | File | Result |
|---|---|---|
| Backend unit/integration/authorization tests + coverage | `pytest-report.txt` | 92 passed, exit 0, 81% line coverage |
| End-to-end workflows with axe WCAG 2 A/AA checks | `e2e-report.txt` | 6/6 passed |
| Assistant evaluation (offline provider) | `assistant-eval.json` | 8/8 metrics pass (numeric accuracy, citation support, refusal recall, false-refusal 0, missing-evidence honesty, authorization, injection, poll accuracy). Limitation: small hand-written refusal set; live LLM not evaluated |
| Forecast evaluation (synthetic XS) | `forecast-eval-xs-2026.{md,json}` | Correctly **blocked**: does not beat uniform-swing baseline |
| Load tests | `loadtest-20u-60s.json`, `loadtest-50u-60s.json` | 0 errors; ~60 req/s saturation on 4 vCPU; p95 941 ms @ 20 users |
| Backup → restore verification | `../operations/backup-restore.md` | All tables matched, RLS + triggers present, tamper test fails as expected |
| Staging-mode configuration (OIDC RS256, dev auth off, non-superuser owner) | `staging-mode-verify.txt` | 9/9 checks pass |
| Dependency audits | CI commands `pip-audit`, `npm audit --omit=dev` | 0 known vulnerabilities after upgrades |
| Secret scan | `/.secrets.baseline` (detect-secrets) | 8 audited dev/test-only values, all allowlisted; runtime guard rejects them in staging/production |
| IaC | `terraform validate`, checkov | Valid; 212 passed / 0 failed with 9 documented exceptions |
