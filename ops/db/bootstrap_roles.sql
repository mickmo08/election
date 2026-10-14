-- Cluster-level roles. Run once per environment by the platform operator (not by migrations).
-- Passwords are supplied via psql variables sourced from the secret manager:
--   psql -v app_pw="$APP_PW" -v worker_pw="$WORKER_PW" -v backup_pw="$BACKUP_PW" -f bootstrap_roles.sql
SELECT 'CREATE ROLE election_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD ' || quote_literal(:'app_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'election_app') \gexec
SELECT 'CREATE ROLE election_worker LOGIN NOSUPERUSER BYPASSRLS PASSWORD ' || quote_literal(:'worker_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'election_worker') \gexec
-- Read-only backup role: BYPASSRLS so logical dumps include every tenant's rows (FORCE RLS applies to owners).
SELECT 'CREATE ROLE election_backup LOGIN NOSUPERUSER BYPASSRLS PASSWORD ' || quote_literal(:'backup_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'election_backup') \gexec
