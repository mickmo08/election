# Deployment guide

## Local development
```bash
# PostgreSQL 16 (PostGIS optional), Python 3.12+, Node 22
psql -v app_pw=election_app -v worker_pw=election_worker -v backup_pw=election_backup -f ops/db/bootstrap_roles.sql
cd backend && uv venv && uv pip install -e '.[dev]' && cp .env.example .env
alembic upgrade head && python -m app.cli seed-demo        # fictional XS dataset + demo tenants/users
uvicorn app.main:app --port 8000 &  python -m app.cli worker &
cd ../frontend && npm ci && npm run build && npm start      # http://localhost:3000 → demo sign-in
```
Or `docker compose up --build` (uses `postgis/postgis:16-3.4`).

## AWS (staging, then production)
Prerequisites (owner: platform team; **costs require approval**): AWS account, Terraform state bucket +
lock table, ACM certificate for the domain, OIDC provider (e.g. Okta/Entra/Auth0/Cognito) with an application
for the API audience, GitHub OIDC deploy role, on-call email.
1. Fill `infra/terraform/envs/<env>.tfvars` and `<env>.backend.hcl` (all `REPLACE_WITH_*` values).
2. `terraform init -backend-config=envs/<env>.backend.hcl && terraform plan -var-file=envs/<env>.tfvars` → review → apply.
3. Bootstrap DB roles once: `psql "<owner url from RDS secret>" -v app_pw=… -v worker_pw=… -v backup_pw=…
   -f ops/db/bootstrap_roles.sql` (passwords from the Secrets Manager entries Terraform created).
4. Put external secrets: `aws secretsmanager put-secret-value --secret-id election-<env>/fec_api_key …`
   (and `anthropic_api_key`, `metrics_token`).
5. Run the `Deploy` workflow with the image tag (git SHA). It snapshots the DB, migrates, rolls out with the ECS
   circuit breaker, and smoke-tests.
6. Allow-list egress for enabled sources (e.g. `api.open.fec.gov`, `www2.census.gov`, `dataverse.harvard.edu`);
   set each source to `active` via the admin API once credentials/licences are in place.
7. Create tenants and memberships (operator), map users from the IdP (users sign in once, admins add roles).

## Configuration reference
All settings are `ELECTION_*` environment variables (`backend/app/config.py`). Staging/production refuse to start
with dev auth secrets, missing OIDC settings, or development database credentials. Synthetic data is refused in
production.
