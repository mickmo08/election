#!/usr/bin/env bash
# Logical backup with an integrity manifest. Production relies primarily on RDS automated backups
# (PITR, 14 days) + cross-region copies; this logical dump is the portable, verifiable second copy
# taken nightly and before risky migrations.
#   Usage: DATABASE_URL=postgresql://owner@host/db ./backup.sh <out-dir> [s3://bucket/prefix]
set -euo pipefail
OUT="${1:?out dir}"; S3="${2:-}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$OUT"
DUMP="$OUT/election-$TS.dump"
pg_dump --format=custom --no-owner --compress=6 --file="$DUMP" "$DATABASE_URL"
SHA=$(sha256sum "$DUMP" | cut -d' ' -f1)
# Manifest: exact row counts for every table + schema version, used by restore_verify.sh.
psql "$DATABASE_URL" -At -F$'\t' -c "
  SELECT 'schema_version', version_num FROM alembic_version
  UNION ALL
  SELECT 'rows:' || c.relname, (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE c.relkind = 'r' AND n.nspname = 'public' ORDER BY 1" > "$OUT/election-$TS.manifest.tsv"
echo -e "sha256\t$SHA" >> "$OUT/election-$TS.manifest.tsv"
echo -e "created_at\t$TS" >> "$OUT/election-$TS.manifest.tsv"
if [ -n "$S3" ]; then
  aws s3 cp "$DUMP" "$S3/" --sse aws:kms
  aws s3 cp "$OUT/election-$TS.manifest.tsv" "$S3/" --sse aws:kms
fi
echo "$DUMP"
