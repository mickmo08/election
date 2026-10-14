# Tenant isolation

* **Database roles** (`ops/db/bootstrap_roles.sql`): `election_app` (API; NOBYPASSRLS), `election_worker`
  (background jobs; BYPASSRLS; never used by request handlers), `election_backup` (read-only, BYPASSRLS),
  schema owner (migrations only).
* **Policies** (`migrations/versions/*_0002_security_controls.py`): every tenant table has `ENABLE` + `FORCE ROW
  LEVEL SECURITY`. Reads are limited to `tenant_id = current_setting('app.tenant_id')` (plus `NULL` platform
  rows for polls/documents); writes must carry the current tenant. The tenant is bound per transaction with
  `set_config('app.tenant_id', …, true)` only after membership is verified.
* **Application** checks permissions per endpoint; RLS is the backstop if a query forgets a filter.
* **Verification**: `tests/test_security.py` runs raw SQL without `WHERE` clauses under another tenant's
  context, attempts cross-tenant inserts and `SET row_security = off`, and exercises the API as a second tenant.
* **Not RLS-scoped**: reference data (countries, districts, results, sources) is platform-wide public research
  data; `users`, `memberships`, `tenants` are accessed only through membership-checked code paths.
