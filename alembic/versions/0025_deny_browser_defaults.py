"""Keep future application tables/views/sequences closed to browser roles."""
from alembic import op

revision = '0025_deny_browser_defaults'
down_revision = '0024_deny_browser_roles'
branch_labels = depends_on = None


def upgrade():
    # Implicit creator is current_user; never alter provider-admin defaults.
    op.execute('''DO $$ DECLARE
      schema_name text;
      grantee text;
    BEGIN
      FOREACH schema_name IN ARRAY ARRAY['public','analytics'] LOOP
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM PUBLIC', schema_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM PUBLIC', schema_name);
        FOR grantee IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
          EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM %I', schema_name, grantee);
          EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM %I', schema_name, grantee);
        END LOOP;
      END LOOP;
    END $$''')


def downgrade():
    # Rolling back a schema must not restore unsafe future grants.
    pass
