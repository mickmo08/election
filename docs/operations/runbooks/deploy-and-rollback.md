# Deploy and rollback

**Deploy** (GitHub Actions `Deploy`, manual dispatch; production requires environment approval):
1. Build/push immutable images tagged with the git SHA.
2. `ops/deploy/run_migrations.sh`: RDS snapshot → one-off ECS task `alembic upgrade head` → abort on failure.
3. `ops/deploy/rollout.sh`: new task definitions for api/worker/web; ECS circuit breaker auto-rolls back if
   health checks (`/readyz` for API, `/login` for web) fail.
4. `ops/deploy/smoke.sh`: login page 200, API requires auth (401).

**Migration policy**: expand/contract. A release may only add nullable columns/tables or backfill; destructive
changes ship one release later. So the previous image always runs against the new schema → app rollback never
requires a schema rollback.

**Rollback**: `./ops/deploy/rollout.sh <env> <previous-sha>`. Schema rollback (rare): `alembic downgrade -1`
run as a one-off task, only after confirming the downgrade is non-destructive; otherwise restore from the
pre-deploy snapshot (`database-restore.md`).
