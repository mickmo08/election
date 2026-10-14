resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = aws_kms_key.main.id
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  alb_dim = { LoadBalancer = aws_lb.main.arn_suffix }
}

# Availability SLO proxy: 5xx ratio at the load balancer.
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 1 # percent
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
  metric_query {
    id          = "rate"
    expression  = "100 * errors / MAX([errors, requests])"
    label       = "5xx %"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      dimensions  = merge(local.alb_dim, { TargetGroup = aws_lb_target_group.tg["api"].arn_suffix })
      period      = 300
      stat        = "Sum"
    }
  }
  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      dimensions  = merge(local.alb_dim, { TargetGroup = aws_lb_target_group.tg["api"].arn_suffix })
      period      = 300
      stat        = "Sum"
    }
  }
}

# Latency SLO: p95 target response time.
resource "aws_cloudwatch_metric_alarm" "api_p95" {
  alarm_name          = "${local.name}-api-p95-latency"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = merge(local.alb_dim, { TargetGroup = aws_lb_target_group.tg["api"].arn_suffix })
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  threshold           = 0.8 # seconds
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  for_each            = aws_lb_target_group.tg
  alarm_name          = "${local.name}-${each.key}-unhealthy"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = merge(local.alb_dim, { TargetGroup = each.value.arn_suffix })
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "db_cpu" {
  alarm_name          = "${local.name}-db-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${local.name}-db-free-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10 * 1024 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# Application metrics (dead letters, freshness breaches, open quarantine) are emitted as
# structured log lines; metric filters turn them into CloudWatch metrics for alarms.
resource "aws_cloudwatch_log_metric_filter" "job_dead" {
  name           = "${local.name}-job-dead"
  log_group_name = aws_cloudwatch_log_group.svc["worker"].name
  pattern        = "{ $.msg = \"job failed\" && $.dead IS TRUE }"
  metric_transformation {
    name      = "DeadLetterJobs"
    namespace = "Election/${var.environment}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "job_dead" {
  alarm_name          = "${local.name}-dead-letter-jobs"
  namespace           = "Election/${var.environment}"
  metric_name         = "DeadLetterJobs"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_log_metric_filter" "ingestion_failed" {
  name           = "${local.name}-ingestion-failed"
  log_group_name = aws_cloudwatch_log_group.svc["worker"].name
  pattern        = "{ $.msg = \"ingestion finished\" && ($.status = \"quarantined\" || $.status = \"failed\") }"
  metric_transformation {
    name      = "IngestionFailures"
    namespace = "Election/${var.environment}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "ingestion_failed" {
  alarm_name          = "${local.name}-ingestion-failures"
  namespace           = "Election/${var.environment}"
  metric_name         = "IngestionFailures"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_log_metric_filter" "freshness" {
  name           = "${local.name}-freshness-breach"
  log_group_name = aws_cloudwatch_log_group.svc["worker"].name
  pattern        = "{ $.msg = \"freshness breach\" }"
  metric_transformation {
    name      = "FreshnessBreaches"
    namespace = "Election/${var.environment}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "freshness" {
  alarm_name          = "${local.name}-freshness-breach"
  namespace           = "Election/${var.environment}"
  metric_name         = "FreshnessBreaches"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
