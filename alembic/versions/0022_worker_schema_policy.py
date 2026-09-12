"""Expose the migration revision through Supabase RLS to the worker."""
from alembic import op


revision = '0022_worker_schema_policy'
down_revision = '0021_worker_schema_readiness'
branch_labels = depends_on = None


def upgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        DROP POLICY IF EXISTS sportsbet_worker_schema_readiness ON public.alembic_version;
        CREATE POLICY sportsbet_worker_schema_readiness ON public.alembic_version
            FOR SELECT TO sportsbet_worker USING (true);
        END IF; END $$""")


def downgrade():
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_schema_readiness ON public.alembic_version')
