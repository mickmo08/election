# Tenant offboarding and data deletion

1. Confirm the request and contractual retention obligations; export data the customer is entitled to.
2. Set the tenant `status` to `suspended` (access stops immediately).
3. As the schema owner (published report versions and audit events are otherwise immutable), run
   `app.services.retention.purge_tenant(db, tenant_id)` in a one-off task; it deletes surveys and responses,
   reports and versions, private polls, assistant logs, exports, usage and memberships, and marks the tenant
   `deleted`. Record the counts returned.
4. Audit events are retained per the platform audit retention policy (legal review pending), then purged via the
   owner-only `app.retention_purge` path.
5. Backups age out per the backup retention window; document this in the deletion confirmation.
