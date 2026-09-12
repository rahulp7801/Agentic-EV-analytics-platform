"""Retain exact evidence for every future verified stat settlement."""
from alembic import op


revision = '0020_settlement_evidence'
down_revision = '0019_prop_quote_provenance'
branch_labels = depends_on = None


def upgrade():
    op.execute('''
        ALTER TABLE analytics.predictions
        ADD COLUMN outcome_evidence TEXT,
        ADD CONSTRAINT ck_verified_settlement_evidence CHECK (
            outcome_source IS DISTINCT FROM 'observed_final_stats'
            OR outcome_evidence IS NOT NULL
        ) NOT VALID
    ''')
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        GRANT UPDATE (outcome_evidence) ON analytics.predictions TO sportsbet_worker;
        END IF; END $$""")


def downgrade():
    op.execute('''
        ALTER TABLE analytics.predictions
        DROP CONSTRAINT ck_verified_settlement_evidence,
        DROP COLUMN outcome_evidence
    ''')
