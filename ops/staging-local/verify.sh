#!/usr/bin/env bash
# Local staging-mode verification: OIDC RS256 auth, dev auth disabled, RBAC, security headers, worker path.
set -uo pipefail
API=${API:-http://localhost:8002}
PY=${PY:-.venv/bin/python}
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1 ($2)"; pass=$((pass+1)); else echo "FAIL $1 (got $2, want $3)"; fail=$((fail+1)); fi; }
ALICE=$($PY ../ops/staging-local/mock_idp.py token alice)
BOB=$($PY ../ops/staging-local/mock_idp.py token bob)
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
check "readyz" "$(code $API/readyz)" 200
check "OIDC RS256 token accepted" "$(code -H "authorization: Bearer $ALICE" -H 'x-tenant: staging-newsroom' $API/api/v1/me)" 200
check "role from membership" "$(curl -s -H "authorization: Bearer $ALICE" -H 'x-tenant: staging-newsroom' $API/api/v1/me | $PY -c 'import sys,json;print(json.load(sys.stdin)["role"])')" admin
check "dev token endpoint disabled" "$(code -XPOST -H 'content-type: application/json' -d '{"subject":"demo-admin"}' $API/api/v1/dev/token)" 404
HS=$($PY -c "import jwt,time;print(jwt.encode({'sub':'alice','iss':'http://localhost:9000','aud':'election-api','exp':int(time.time())+60},'guess-the-secret-guess-the-secret!!',algorithm='HS256'))")
check "HS256 token refused" "$(code -H "authorization: Bearer $HS" -H 'x-tenant: staging-newsroom' $API/api/v1/me)" 401
check "viewer cannot read audit" "$(code -H "authorization: Bearer $BOB" -H 'x-tenant: staging-newsroom' $API/api/v1/admin/audit)" 403
check "HSTS header" "$(curl -s -D - -o /dev/null $API/healthz | grep -ci strict-transport-security)" 1
check "synthetic data labelled in staging" "$(curl -s -H "authorization: Bearer $ALICE" -H 'x-tenant: staging-newsroom' "$API/api/v1/contests?country=XS&cycle=2024&office=xs_assembly&limit=1" | $PY -c 'import sys,json;print(json.load(sys.stdin)["is_synthetic"])')" True
JOB=$(curl -s -XPOST -H "authorization: Bearer $ALICE" -H 'x-tenant: staging-newsroom' -H 'content-type: application/json' -d '{"country":"XS","office":"xs_assembly","cycle":2026}' $API/api/v1/admin/forecasts | $PY -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
(set -a; . /tmp/claude-0/staging.env; set +a; $PY -m app.cli worker --once >/dev/null 2>&1)
check "forecast job processed by worker" "$(curl -s -H "authorization: Bearer $ALICE" -H 'x-tenant: staging-newsroom' $API/api/v1/admin/jobs/$JOB | $PY -c 'import sys,json;print(json.load(sys.stdin)["status"])')" succeeded
echo "passed=$pass failed=$fail"
[ $fail = 0 ]
