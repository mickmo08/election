# Application secrets. Values for external credentials are set out-of-band (never in Terraform state):
#   aws secretsmanager put-secret-value --secret-id <name> --secret-string ...
locals {
  external_secrets = {
    fec_api_key       = "api.data.gov key for OpenFEC"
    anthropic_api_key = "LLM provider key (optional; assistant falls back to deterministic composer)"
    metrics_token     = "Shared token for /metrics scraping"
  }
}

resource "aws_secretsmanager_secret" "external" {
  for_each    = local.external_secrets
  name        = "${local.name}/${each.key}"
  description = each.value
  kms_key_id  = aws_kms_key.main.arn
}

# Passwords for the RLS-subject app role and the worker role (created by ops/db/bootstrap_roles.sql).
data "aws_secretsmanager_random_password" "db" {
  for_each            = toset(["app", "worker"])
  password_length     = 40
  exclude_punctuation = true
}

resource "aws_secretsmanager_secret" "db" {
  for_each   = toset(["app", "worker"])
  name       = "${local.name}/db_${each.key}_password"
  kms_key_id = aws_kms_key.main.arn
}

resource "aws_secretsmanager_secret_version" "db" {
  for_each      = toset(["app", "worker"])
  secret_id     = aws_secretsmanager_secret.db[each.key].id
  secret_string = data.aws_secretsmanager_random_password.db[each.key].random_password
  lifecycle { ignore_changes = [secret_string] } # rotated operationally (runbook: secret-rotation)
}
