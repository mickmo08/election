# Secret rotation

* RDS master/owner: managed by RDS in Secrets Manager (`manage_master_user_password`), rotation enabled there.
* App/worker/backup role passwords: generate new value → `ALTER ROLE election_app PASSWORD '…'` (owner) →
  `aws secretsmanager put-secret-value` → force new ECS deployment (tasks read secrets at start). Rotate
  quarterly and after any suspected exposure. (Automated rotation Lambda: follow-up, see IaC exceptions.)
* FEC/LLM API keys: create a new key with the provider → put secret value → redeploy → revoke old key.
* OIDC signing keys: owned by the IdP; JWKS is cached for 1 h — no action needed beyond IdP rotation.
