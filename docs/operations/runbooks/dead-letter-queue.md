# Dead-letter jobs

Alarm `*-dead-letter-jobs` fires when a job exhausts retries (default 5, exponential backoff 15 s → 1 h).
1. `GET /api/v1/admin/jobs?status=dead` (or Administration → Operations): read `last_error`.
2. Transient upstream issue resolved? `POST /api/v1/admin/jobs/{id}/requeue`.
3. Source unavailable (credentials/licence/network)? Jobs for unavailable sources return `unavailable` without
   retrying; fix the source status/remediation instead.
4. Code bug: fix, deploy, then requeue. Jobs are idempotent (ingestion idempotency key = source + adapter
   version + params + file hashes), so requeue is safe.
5. Worker crash mid-job: jobs whose heartbeat is older than 15 minutes are re-claimed automatically.
