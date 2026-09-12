"""Let the restricted worker verify the deployed migration revision."""
from alembic import op


revision = '0021_worker_schema_readiness'
down_revision = '0020_settlement_evidence'
branch_labels = depends_on = None


def upgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        GRANT SELECT ON public.alembic_version TO sportsbet_worker;
        END IF; END $$""")


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        REVOKE SELECT ON public.alembic_version FROM sportsbet_worker;
        END IF; END $$""")
