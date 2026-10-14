# Threat model (STRIDE)

Assets: tenant research (drafts, survey microdata, assistant history, private polls), integrity of published
results/forecasts/reports, source credentials, platform availability on election night, public trust.
Actors: anonymous internet users; authenticated users of another tenant; malicious insider within a tenant;
compromised upstream data source; prompt-injection content in ingested text; compromised dependency; operators.

| Threat | Vector | Controls (implemented) | Evidence | Residual risk / follow-up |
|---|---|---|---|---|
| **S**poofing users | Forged/expired JWT, `alg:none`, HS256 in prod | OIDC RS*/ES* via JWKS, `exp/iss/aud` required; HS256 dev tokens refused outside dev/test (config + runtime) | `test_forged_and_expired_tokens_rejected`, `test_oidc_rs256_validation`, `test_dev_token_refused_outside_dev` | IdP account security is the customer's/IdP's |
| Spoofing tenant | Setting `X-Tenant` to another org | Membership check per request; identical 403 for unknown vs non-member tenants; SSO issuer pinning per tenant | `test_unauthenticated_and_tenant_header` | — |
| **T**ampering with history | Editing results, audit trail, raw files, published reports | Append-only triggers; app role lacks UPDATE/DELETE grants; published report versions immutable; raw S3 Object Lock | `test_app_role_cannot_tamper_with_history`, `test_raw_files_are_immutable`, report tests | Owner role can purge (documented runbook only) |
| Tampering via sources | Poisoned/changed upstream files | Content hashes, schema validation, totals checks, status-transition rules, quarantine with human review | ingestion tests | Sophisticated plausible falsification needs editorial cross-checks |
| **R**epudiation | Denying exports/publication/role changes | Audit events with actor, request id, IP, outcome; tenant-scoped read | report/export tests | Audit export to WORM storage (follow-up) |
| **I**nformation disclosure across tenants | Missing `WHERE tenant_id` in code | RLS (FORCE) on all tenant tables; app role cannot disable RLS; raw-SQL tests | `test_rls_enforced_in_database_without_app_filters`, `test_cross_tenant_isolation_api` | — |
| Disclosure of respondents | Small cells, row access | No row endpoints; suppression + complementary suppression; base-n bands; identifier/email/phone rejection on import | `test_survey_rows_never_exposed`, `test_upload_protections` | Differencing across many crosstabs (rate-limit + audit; formal SDC review recommended) |
| Disclosure via assistant | Model reads another tenant's data | Tools run on the caller's RLS session; model has no SQL; eval case | `test_private_tenant_poll_not_visible_to_other_tenant`, assistant eval `authorization=1.0` | — |
| Prompt injection | Instructions in pollster wording/documents | Tool output sanitised; system prompt treats tool content as data; tools read-only; grounding check; no write tools | `test_injection_text_is_neutralised` | Novel phrasing may bypass the pattern list; impact limited to answer text |
| Secret leakage | API keys in provenance/logs | FEC key redacted from stored URL and bytes; secrets in Secrets Manager; log redaction of `authorization` at WAF | `test_fec_page_processing_and_secret_redaction`, gitleaks/detect-secrets | — |
| **D**oS / cost abuse | Floods, expensive assistant calls, huge uploads | WAF rate rule; per-instance token buckets; assistant per-user limit; quotas (402); 25 MB uploads; zip-bomb guard; LLM timeouts & tool-call caps | `test_rate_limit`, `test_quota_enforced`, upload tests, load test | Per-instance limiter scales with replicas (WAF is the global control) |
| **E**levation of privilege | Viewer → publisher; tenant admin → operator | Permission matrix; separation of duties on review; operator flag separate from tenant roles | `test_role_matrix`, `test_tenant_admin_is_not_platform_operator`, `test_author_cannot_self_review` | — |
| Misleading output | Synthetic shown as real; LLM-called races; online sentiment as opinion | Fictional synthetic country + banners + publication block; race calls only from authorized sources; issue views labelled frequency-only | e2e tests | Editorial training |
| Supply chain | Vulnerable/malicious dependency | Pinned versions, lockfile, pip-audit, npm audit, ECR scan on push | CI | SBOM + signature verification (follow-up) |
