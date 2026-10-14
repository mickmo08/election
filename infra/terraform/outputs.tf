output "alb_dns_name" { value = aws_lb.main.dns_name }
output "db_endpoint" { value = aws_db_instance.main.address }
output "raw_bucket" { value = aws_s3_bucket.raw.bucket }
output "ecr_repositories" { value = { for k, r in aws_ecr_repository.repos : k => r.repository_url } }
output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
