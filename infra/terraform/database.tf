resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "pg16" {
  name   = "${local.name}-pg16"
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_instance" "main" {
  identifier                          = local.name
  engine                              = "postgres"
  engine_version                      = "16"
  instance_class                      = var.db_instance_class
  allocated_storage                   = var.db_allocated_storage_gb
  max_allocated_storage               = var.db_allocated_storage_gb * 4
  storage_type                        = "gp3"
  storage_encrypted                   = true
  kms_key_id                          = aws_kms_key.main.arn
  db_name                             = "election"
  username                            = "election_owner"
  manage_master_user_password         = true # master secret generated and rotated in Secrets Manager
  master_user_secret_kms_key_id       = aws_kms_key.main.arn
  multi_az                            = var.environment == "production"
  db_subnet_group_name                = aws_db_subnet_group.main.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  parameter_group_name                = aws_db_parameter_group.pg16.name
  backup_retention_period             = var.db_backup_retention_days # point-in-time recovery window
  backup_window                       = "07:00-08:00"
  maintenance_window                  = "sun:08:30-sun:09:30"
  copy_tags_to_snapshot               = true
  deletion_protection                 = true
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${local.name}-final"
  performance_insights_enabled        = true
  performance_insights_kms_key_id     = aws_kms_key.main.arn
  monitoring_interval                 = 60
  monitoring_role_arn                 = aws_iam_role.rds_monitoring.arn
  enabled_cloudwatch_logs_exports     = ["postgresql", "upgrade"]
  auto_minor_version_upgrade          = true
  iam_database_authentication_enabled = true
  apply_immediately                   = false
}

resource "aws_iam_role" "rds_monitoring" {
  name = "${local.name}-rds-monitoring"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "monitoring.rds.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# Cross-region copy of automated backups for regional disaster recovery (production only).
resource "aws_db_instance_automated_backups_replication" "dr" {
  count                  = var.environment == "production" ? 1 : 0
  provider               = aws.dr
  source_db_instance_arn = aws_db_instance.main.arn
  retention_period       = var.db_backup_retention_days
  kms_key_id             = aws_kms_key.dr[0].arn
}

provider "aws" {
  alias  = "dr"
  region = var.region == "us-east-1" ? "us-west-2" : "us-east-1"
}

resource "aws_kms_key" "dr" {
  count               = var.environment == "production" ? 1 : 0
  provider            = aws.dr
  description         = "${local.name} DR backup encryption"
  enable_key_rotation = true
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid    = "Root", Effect = "Allow", Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" },
    Action = "kms:*", Resource = "*"
  }] })
}
