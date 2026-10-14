# Backup and restore

## Layers
1. **RDS automated backups + PITR** (14-day window, `backup_retention_period`), encrypted with KMS; production
   copies automated backups to a second region (`aws_db_instance_automated_backups_replication`).
2. **Pre-deploy snapshots** taken by `ops/deploy/run_migrations.sh` before every migration.
3. **Nightly logical dump** `ops/backup/backup.sh` (custom format) with a manifest of exact per-table row counts,
   schema version and SHA-256; uploaded to S3 with KMS. Runs as the read-only `election_backup` role (BYPASSRLS)
   because FORCE RLS would otherwise filter tenant rows from an owner-run dump on RDS.
4. **Raw source files** in S3 with versioning + Object Lock: every ingestion can be replayed from raw.

## Restore verification (tested)
`ops/backup/restore_verify.sh <dump> <manifest>` verifies the checksum, restores into a scratch database, and
checks schema version, exact row counts for every table, RLS on tenant tables, immutability triggers, and
referential integrity; it exits non-zero on any mismatch and reports restore time.

Evidence (2026-10-14, sandbox, demo dataset incl. tenant rows, run as `election_backup`):
```
RESTORE VERIFY OK: schema 0002, 47 tables matched, RLS tables 10, immutability triggers 5, restore 0.6s
```
A deliberately corrupted dump failed the checksum step (tamper test).

## Not yet verified
RDS point-in-time restore and cross-region restore drills require the AWS environment (cost approval and
credentials pending). Schedule: quarterly restore drill per runbook `runbooks/database-restore.md`.
