variable "environment" {
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production"
  }
}
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}
variable "domain_name" { type = string }
variable "acm_certificate_arn" { type = string }
variable "image_tag" { type = string }
variable "ecr_registry" { type = string }
variable "db_instance_class" {
  type    = string
  default = "db.r6g.large"
}
variable "db_allocated_storage_gb" {
  type    = number
  default = 100
}
variable "db_backup_retention_days" {
  type    = number
  default = 14
}
variable "api_desired_count" {
  type    = number
  default = 2
}
variable "api_max_count" {
  type    = number
  default = 8
}
variable "worker_desired_count" {
  type    = number
  default = 2
}
variable "web_desired_count" {
  type    = number
  default = 2
}
variable "oidc_issuer" { type = string }
variable "oidc_audience" { type = string }
variable "oidc_jwks_url" { type = string }
variable "alarm_email" { type = string }
variable "waf_rate_limit_per_5min" {
  type    = number
  default = 2000
}
variable "raw_object_lock_days" {
  description = "Governance-mode retention for raw source files (immutability)."
  type        = number
  default     = 3650
}
