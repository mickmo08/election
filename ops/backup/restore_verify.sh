#!/usr/bin/env bash
# Restores a dump into a scratch database and verifies it against the backup manifest.
# Proves the backup is usable and measures restore time (RTO evidence). Exit code != 0 on any mismatch.
#   Usage: ADMIN_URL=postgresql://owner@host/postgres ./restore_verify.sh <dump> <manifest>
set -euo pipefail
DUMP="$1"; MANIFEST="$2"
SCRATCH="restore_verify_$(date +%s)"
BASE="${ADMIN_URL%/*}"
TARGET="$BASE/$SCRATCH"
fail() { echo "RESTORE VERIFY FAILED: $*"; psql "$ADMIN_URL" -qc "DROP DATABASE IF EXISTS $SCRATCH" || true; exit 1; }

EXPECTED_SHA=$(awk -F'\t' '$1=="sha256"{print $2}' "$MANIFEST")
[ "$(sha256sum "$DUMP" | cut -d' ' -f1)" = "$EXPECTED_SHA" ] || fail "dump checksum mismatch"

START=$(date +%s.%N)
psql "$ADMIN_URL" -qc "CREATE DATABASE $SCRATCH"
pg_restore --no-owner --exit-on-error --dbname="$TARGET" "$DUMP" || fail "pg_restore error"
END=$(date +%s.%N)

# 1. Schema version
want=$(awk -F'\t' '$1=="schema_version"{print $2}' "$MANIFEST")
got=$(psql "$TARGET" -At -c "SELECT version_num FROM alembic_version")
[ "$want" = "$got" ] || fail "schema version $got != $want"
# 2. Exact row counts per table
mismatch=0
while IFS=$'\t' read -r key val; do
  [[ "$key" == rows:* ]] || continue
  t="${key#rows:}"
  n=$(psql "$TARGET" -At -c "SELECT count(*) FROM \"$t\"")
  [ "$n" = "$val" ] || { echo "row count mismatch $t: $n != $val"; mismatch=1; }
done < "$MANIFEST"
[ $mismatch = 0 ] || fail "row counts differ"
# 3. Security controls survived the restore (RLS, append-only triggers)
rls=$(psql "$TARGET" -At -c "SELECT count(*) FROM pg_class WHERE relrowsecurity AND relforcerowsecurity")
[ "$rls" -ge 10 ] || fail "row-level security missing on restored tables ($rls)"
trg=$(psql "$TARGET" -At -c "SELECT count(*) FROM pg_trigger WHERE tgname LIKE '%append_only' OR tgname = 'report_versions_immutable'")
[ "$trg" -ge 5 ] || fail "immutability triggers missing ($trg)"
# 4. Referential sanity: every result line points at an existing snapshot
orphans=$(psql "$TARGET" -At -c "SELECT count(*) FROM result_lines l LEFT JOIN result_snapshots s ON s.id = l.snapshot_id WHERE s.id IS NULL")
[ "$orphans" = 0 ] || fail "orphaned result lines: $orphans"

psql "$ADMIN_URL" -qc "DROP DATABASE $SCRATCH"
printf 'RESTORE VERIFY OK: schema %s, %s tables matched, RLS tables %s, immutability triggers %s, restore %.1fs\n' \
  "$got" "$(grep -c '^rows:' "$MANIFEST")" "$rls" "$trg" "$(echo "$END - $START" | bc)"
