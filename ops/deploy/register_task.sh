#!/usr/bin/env bash
# Clones the current task definition for a service with a new image tag (and optional command override).
set -euo pipefail
ENV="$1"; TAG="$2"; ROLE="$3"
FAMILY="election-${ENV}-$([ "$ROLE" = migrate ] && echo api || echo "$ROLE")"
CUR=$(aws ecs describe-task-definition --task-definition "$FAMILY" --query taskDefinition --output json)
IMAGE=$(echo "$CUR" | jq -r '.containerDefinitions[0].image' | sed "s/:[^:]*$/:${TAG}/")
NEW=$(echo "$CUR" | jq --arg img "$IMAGE" --arg role "$ROLE" '
  .containerDefinitions[0].image = $img
  | if $role == "migrate" then .containerDefinitions[0].command = ["alembic","upgrade","head"] | .family = (.family + "-migrate") else . end
  | del(.taskDefinitionArn,.revision,.status,.requiresAttributes,.compatibilities,.registeredAt,.registeredBy)')
aws ecs register-task-definition --cli-input-json "$NEW" --query 'taskDefinition.taskDefinitionArn' --output text
