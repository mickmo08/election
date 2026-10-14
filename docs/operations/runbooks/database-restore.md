# Database restore

**Point-in-time (RDS)**: `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier
election-<env> --target-db-instance-identifier election-<env>-restore --restore-time <UTC>`; verify; then
switch services by updating the DB host secret/env and redeploying, or rename instances during a maintenance
window. Target RTO ≤ 1 h (not yet drilled in AWS).

**Logical dump**: `ADMIN_URL=... ./ops/backup/restore_verify.sh <dump> <manifest>` proves the dump; to restore
for real, `pg_restore --no-owner -d <target>` as the schema owner after bootstrapping roles
(`ops/db/bootstrap_roles.sql`), then run `alembic current` to confirm the schema version.

**After any restore**: re-run ingestion for sources whose `last_success_at` is after the restore point (raw
files are in S3, so runs are replayable and idempotent); check quarantine; announce data window affected.

**Drill**: quarterly; record restore duration and verification output in `docs/evidence/`.
