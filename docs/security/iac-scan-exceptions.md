# IaC scan exceptions (Checkov)

Result: 212 passed, 0 failed with the exceptions below (`infra/terraform/.checkov.yaml`).

| Check | Decision | Owner / follow-up |
|---|---|---|
| CKV_AWS_150 ALB deletion protection | Enabled in production via `var.environment`; static scan cannot evaluate | — |
| CKV_AWS_157 RDS Multi-AZ | Production Multi-AZ; staging single-AZ for cost | — |
| CKV_AWS_394 AZ pinning | Two AZs chosen at creation; subnets pin placement | — |
| CKV2_AWS_62 S3 event notifications | No consumer | — |
| CKV2_AWS_76 Log4j AMR | KnownBadInputs rule group (includes Log4j rules) attached | — |
| CKV2_AWS_57 Secret rotation | External API keys rotate manually; DB role rotation Lambda not yet built | Platform team (follow-up) |
| CKV_AWS_144 S3 cross-region replication | Pending cost/product decision; RDS backups replicated cross-region in production | Product + platform |
| CKV_AWS_378 HTTP to targets | TLS terminates at ALB; private subnets only | Accepted risk |
| CKV_AWS_145 Access-log bucket KMS | ALB log delivery requires SSE-S3 | — |
