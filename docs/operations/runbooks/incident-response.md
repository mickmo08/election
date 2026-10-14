# Incident response

1. **Acknowledge** the alert (SNS → on-call). Open an incident channel; assign incident commander + scribe.
2. **Classify**: SEV1 = election-night results unavailable/wrong or cross-tenant exposure; SEV2 = degraded API
   or stale official data > SLA; SEV3 = single source/feature degraded.
3. **Diagnose** with structured logs (CloudWatch Logs Insights: filter by `request_id`, `tenant_id`, `msg`),
   ALB 5xx/latency alarms, `GET /api/v1/admin/ops/status` (queue, dead letters, freshness, quarantine).
4. **Mitigate** first: roll back (`deploy-and-rollback.md`), scale API tasks, disable a misbehaving source
   (`POST /api/v1/admin/sources/{key}/status {"status":"disabled"}`), or set the LLM provider to `offline`.
5. **Wrong published data**: never edit history. Publish a correction snapshot/report version with a note
   (`data-correction.md`); notify affected tenants.
6. **Suspected data exposure**: preserve audit logs, rotate credentials (`secret-rotation.md`), involve legal;
   notification obligations require legal review.
7. **Post-incident review** within 5 business days: timeline, root cause, action items with owners.
