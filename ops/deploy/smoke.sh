#!/usr/bin/env bash
set -euo pipefail
BASE="$1"
curl -fsS "$BASE/login" >/dev/null
test "$(curl -sS "$BASE/api/v1/countries" -o /dev/null -w "%{http_code}")" = 401  # auth enforced
echo "smoke OK: $BASE"
