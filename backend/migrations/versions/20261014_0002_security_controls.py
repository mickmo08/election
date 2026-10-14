"""Row-level security, append-only audit, immutable result history, grants, optional PostGIS.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TENANT_TABLES_NULLABLE = ("polls", "documents")  # NULL tenant = platform-wide shared data
TENANT_TABLES_STRICT = (
    "survey_datasets", "survey_responses", "assistant_queries", "reports",
    "report_versions", "usage_events", "exports",
)
TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
APP_ROLES = ("election_app", "election_worker")


def _if_role(role: str, sql: str) -> str:
    return f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN {sql}; END IF; END $$;"


def upgrade() -> None:
    # --- RLS: tenant-owned rows -------------------------------------------------
    for t in TENANT_TABLES_NULLABLE + TENANT_TABLES_STRICT + ("audit_events",):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    for t in TENANT_TABLES_NULLABLE:
        op.execute(f"CREATE POLICY tenant_read ON {t} FOR SELECT USING (tenant_id IS NULL OR tenant_id = {TENANT_EXPR})")
        op.execute(f"CREATE POLICY tenant_insert ON {t} FOR INSERT WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"CREATE POLICY tenant_update ON {t} FOR UPDATE USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"CREATE POLICY tenant_delete ON {t} FOR DELETE USING (tenant_id = {TENANT_EXPR})")
    for t in TENANT_TABLES_STRICT:
        op.execute(f"CREATE POLICY tenant_all ON {t} USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
    # Audit: tenants read their own events; inserts may carry their tenant or none (platform events).
    op.execute(f"CREATE POLICY audit_read ON audit_events FOR SELECT USING (tenant_id = {TENANT_EXPR})")
    op.execute(f"CREATE POLICY audit_insert ON audit_events FOR INSERT WITH CHECK (tenant_id IS NULL OR tenant_id = {TENANT_EXPR})")

    # --- Append-only audit trail ----------------------------------------------
    op.execute("""
    CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF current_setting('app.retention_purge', true) = 'on' AND TG_OP = 'DELETE'
         AND pg_has_role(current_user, (SELECT tableowner FROM pg_tables WHERE tablename = TG_TABLE_NAME AND schemaname = TG_TABLE_SCHEMA), 'MEMBER') THEN
        RETURN OLD;  -- documented retention purge, schema owner only
      END IF;
      RAISE EXCEPTION '% on % is not permitted (append-only)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
    END $$;
    """)
    for t in ("audit_events", "result_snapshots", "result_lines", "raw_files"):
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION forbid_mutation()")

    # Published report versions are immutable; corrections create a new version.
    op.execute("""
    CREATE OR REPLACE FUNCTION protect_published_report_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND current_setting('app.retention_purge', true) = 'on'
         AND pg_has_role(current_user, (SELECT tableowner FROM pg_tables WHERE tablename = TG_TABLE_NAME AND schemaname = TG_TABLE_SCHEMA), 'MEMBER') THEN
        RETURN OLD;  -- tenant deletion by schema owner (runbook: tenant-offboarding)
      END IF;
      IF OLD.published_at IS NOT NULL THEN
        RAISE EXCEPTION 'published report versions are immutable' USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN COALESCE(NEW, OLD);
    END $$;
    """)
    op.execute("CREATE TRIGGER report_versions_immutable BEFORE UPDATE OR DELETE ON report_versions "
               "FOR EACH ROW EXECUTE FUNCTION protect_published_report_version()")

    # --- Grants -----------------------------------------------------------------
    for role in APP_ROLES:
        op.execute(_if_role(role, f"GRANT USAGE ON SCHEMA public TO {role}"))
        op.execute(_if_role(role, f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"))
        op.execute(_if_role(role, f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))
        op.execute(_if_role(role, f"REVOKE UPDATE, DELETE ON audit_events, result_snapshots, result_lines, raw_files FROM {role}"))
        op.execute(_if_role(role, f"REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {role}"))

    # --- Optional PostGIS spatial index ----------------------------------------
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'postgis') THEN
        CREATE EXTENSION IF NOT EXISTS postgis;
        ALTER TABLE districts ADD COLUMN geom geometry(MultiPolygon, 4326)
          GENERATED ALWAYS AS (ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(geometry::text), 4326))) STORED;
        CREATE INDEX ix_districts_geom ON districts USING gist (geom);
      END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='districts' AND column_name='geom') THEN
        ALTER TABLE districts DROP COLUMN geom;
      END IF;
    END $$;
    """)
    op.execute("DROP TRIGGER IF EXISTS report_versions_immutable ON report_versions")
    op.execute("DROP FUNCTION IF EXISTS protect_published_report_version()")
    for t in ("audit_events", "result_snapshots", "result_lines", "raw_files"):
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t}")
    op.execute("DROP FUNCTION IF EXISTS forbid_mutation()")
    for t in TENANT_TABLES_NULLABLE:
        for p in ("tenant_read", "tenant_insert", "tenant_update", "tenant_delete"):
            op.execute(f"DROP POLICY IF EXISTS {p} ON {t}")
    for t in TENANT_TABLES_STRICT:
        op.execute(f"DROP POLICY IF EXISTS tenant_all ON {t}")
    op.execute("DROP POLICY IF EXISTS audit_read ON audit_events")
    op.execute("DROP POLICY IF EXISTS audit_insert ON audit_events")
    for t in TENANT_TABLES_NULLABLE + TENANT_TABLES_STRICT + ("audit_events",):
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
