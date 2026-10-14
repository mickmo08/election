#!/usr/bin/env bash
# Deploys api, worker and web. ECS deployment circuit breaker (rollback=true) reverts on failed health checks.
# Manual rollback: ./ops/deploy/rollout.sh <env> <previous-tag>  (schema migrations are backward compatible
# for one release by policy, see docs/operations/runbooks/deploy-and-rollback.md).
set -euo pipefail
ENV="$1"; TAG="$2"
for SVC in api worker web; do
  TD=$(./ops/deploy/register_task.sh "$ENV" "$TAG" "$SVC")
  aws ecs update-service --cluster "election-${ENV}" --service "election-${ENV}-${SVC}" --task-definition "$TD" >/dev/null
done
aws ecs wait services-stable --cluster "election-${ENV}" --services "election-${ENV}-api" "election-${ENV}-worker" "election-${ENV}-web"
