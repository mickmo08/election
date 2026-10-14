resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "svc" {
  for_each          = toset(["api", "worker", "web", "scheduler"])
  name              = "/${local.name}/${each.key}"
  retention_in_days = 400
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_iam_role" "execution" {
  name = "${local.name}-ecs-execution"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"],
    Resource = concat([for s in aws_secretsmanager_secret.external : s.arn], [for s in aws_secretsmanager_secret.db : s.arn]) },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = [aws_kms_key.main.arn] },
  ] })
}

resource "aws_iam_role" "task" {
  name = "${local.name}-task"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}

resource "aws_iam_role_policy" "task_s3" {
  role = aws_iam_role.task.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    # Write-once raw store: Put/Get/Head only; no Delete permission for the application.
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.raw.arn}/*" },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.raw.arn },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = [aws_kms_key.main.arn] },
  ] })
}

locals {
  db_host = aws_db_instance.main.address
  common_env = [
    { name = "ELECTION_ENVIRONMENT", value = var.environment },
    { name = "ELECTION_STORAGE_BACKEND", value = "s3" },
    { name = "ELECTION_STORAGE_S3_BUCKET", value = aws_s3_bucket.raw.bucket },
    { name = "ELECTION_OIDC_ISSUER", value = var.oidc_issuer },
    { name = "ELECTION_OIDC_AUDIENCE", value = var.oidc_audience },
    { name = "ELECTION_OIDC_JWKS_URL", value = var.oidc_jwks_url },
    { name = "ELECTION_CORS_ORIGINS", value = jsonencode(["https://${var.domain_name}"]) },
    { name = "ELECTION_DB_HOST", value = local.db_host },
  ]
  common_secrets = [
    { name = "ELECTION_DB_APP_PASSWORD", valueFrom = aws_secretsmanager_secret.db["app"].arn },
    { name = "ELECTION_DB_WORKER_PASSWORD", valueFrom = aws_secretsmanager_secret.db["worker"].arn },
    { name = "ELECTION_DB_OWNER_SECRET", valueFrom = aws_db_instance.main.master_user_secret[0].secret_arn },
    { name = "ELECTION_FEC_API_KEY", valueFrom = aws_secretsmanager_secret.external["fec_api_key"].arn },
    { name = "ELECTION_ANTHROPIC_API_KEY", valueFrom = aws_secretsmanager_secret.external["anthropic_api_key"].arn },
    { name = "ELECTION_METRICS_TOKEN", valueFrom = aws_secretsmanager_secret.external["metrics_token"].arn },
  ]
  services = {
    api       = { cpu = 1024, memory = 2048, port = 8000, command = null, image = "election-api" }
    worker    = { cpu = 1024, memory = 2048, port = null, command = ["python", "-m", "app.cli", "worker"], image = "election-api" }
    web       = { cpu = 512, memory = 1024, port = 3000, command = null, image = "election-web" }
    scheduler = { cpu = 256, memory = 512, port = null, command = ["python", "-m", "app.cli", "schedule"], image = "election-api" }
  }
}

resource "aws_ecs_task_definition" "svc" {
  for_each                 = local.services
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name                   = each.key
    image                  = "${var.ecr_registry}/${each.value.image}-${var.environment}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = each.key != "web"
    command                = each.value.command
    # Entrypoint wrapper (ops/deploy/entrypoint.sh) assembles DB URLs from the injected secrets.
    environment     = each.key == "web" ? [{ name = "ELECTION_API_ORIGIN", value = "http://api.${local.name}.internal:8000" }] : local.common_env
    secrets         = each.key == "web" ? [] : local.common_secrets
    portMappings    = each.value.port == null ? [] : [{ containerPort = each.value.port, protocol = "tcp" }]
    linuxParameters = { initProcessEnabled = true }
    logConfiguration = {
      logDriver = "awslogs"
      options = { awslogs-group = aws_cloudwatch_log_group.svc[each.key].name, awslogs-region = var.region,
      awslogs-stream-prefix = each.key }
    }
  }])
}

resource "aws_service_discovery_private_dns_namespace" "internal" {
  name = "${local.name}.internal"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "api" {
  name = "api"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.internal.id
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

resource "aws_ecs_service" "svc" {
  for_each        = { for k, v in local.services : k => v if k != "scheduler" }
  name            = "${local.name}-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.svc[each.key].arn
  desired_count   = each.key == "api" ? var.api_desired_count : each.key == "worker" ? var.worker_desired_count : var.web_desired_count
  launch_type     = "FARGATE"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.services.id]
    assign_public_ip = false
  }
  dynamic "load_balancer" {
    for_each = each.key == "worker" ? [] : [1]
    content {
      target_group_arn = aws_lb_target_group.tg[each.key].arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }
  dynamic "service_registries" {
    for_each = each.key == "api" ? [1] : []
    content { registry_arn = aws_service_discovery_service.api.arn }
  }
  lifecycle { ignore_changes = [task_definition, desired_count] } # managed by deploy pipeline / autoscaling
}

resource "aws_appautoscaling_target" "api" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.svc["api"].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.api_desired_count
  max_capacity       = var.api_max_count
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.name}-api-cpu"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  policy_type        = "TargetTrackingScaling"
  target_tracking_scaling_policy_configuration {
    target_value = 55
    predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
  }
}

# Scheduler: enqueue due ingestion/freshness/retention jobs every 5 minutes.
resource "aws_iam_role" "events" {
  name = "${local.name}-events"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}

resource "aws_iam_role_policy" "events" {
  role = aws_iam_role.events.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "ecs:RunTask", Resource = aws_ecs_task_definition.svc["scheduler"].arn },
    { Effect = "Allow", Action = "iam:PassRole", Resource = [aws_iam_role.execution.arn, aws_iam_role.task.arn] },
  ] })
}

resource "aws_cloudwatch_event_rule" "scheduler" {
  name                = "${local.name}-scheduler"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "scheduler" {
  rule     = aws_cloudwatch_event_rule.scheduler.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.events.arn
  ecs_target {
    task_definition_arn = aws_ecs_task_definition.svc["scheduler"].arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = aws_subnet.private[*].id
      security_groups = [aws_security_group.services.id]
    }
  }
}
