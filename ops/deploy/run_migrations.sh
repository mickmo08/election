#!/usr/bin/env bash
# Runs a pre-migration snapshot and `alembic upgrade head` as a one-off ECS task using the new image.
set -euo pipefail
ENV="$1"; TAG="$2"
CLUSTER="election-${ENV}"
aws rds create-db-snapshot --db-instance-identifier "election-${ENV}" \
  --db-snapshot-identifier "pre-deploy-${TAG:0:12}-$(date +%Y%m%d%H%M)" >/dev/null
aws rds wait db-snapshot-available --db-instance-identifier "election-${ENV}"
TASK_DEF=$(./ops/deploy/register_task.sh "$ENV" "$TAG" migrate)
NET=$(aws ecs describe-services --cluster "$CLUSTER" --services "election-${ENV}-api" \
  --query 'services[0].networkConfiguration' --output json)
ARN=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$TASK_DEF" --launch-type FARGATE \
  --network-configuration "$NET" --query 'tasks[0].taskArn' --output text)
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$ARN"
CODE=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$ARN" --query 'tasks[0].containers[0].exitCode' --output text)
[ "$CODE" = "0" ] || { echo "migration failed (exit $CODE); services NOT rolled out"; exit 1; }
