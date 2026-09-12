"""Require provenance for future prediction settlements."""
from alembic import op

revision='0015_settlement_provenance'
down_revision='0014_prop_snapshot_integrity'
branch_labels=depends_on=None


def upgrade():
    op.execute('ALTER TABLE analytics.predictions ADD COLUMN outcome_source TEXT')
    op.execute('ALTER TABLE analytics.predictions ADD COLUMN outcome_ref TEXT')
    op.execute('ALTER TABLE analytics.predictions ADD COLUMN outcome_observed_at TIMESTAMPTZ')
    op.execute('ALTER TABLE analytics.predictions ADD COLUMN actual_value NUMERIC')
    op.execute("""ALTER TABLE analytics.predictions ADD CONSTRAINT ck_prediction_settlement_evidence CHECK (
        outcome IS NULL OR (outcome IN ('true','false','\"push\"','\"void\"','null')
        AND LENGTH(outcome_source) BETWEEN 1 AND 40 AND LENGTH(outcome_ref) BETWEEN 1 AND 200
        AND outcome_observed_at IS NOT NULL AND (actual_value IS NULL OR (actual_value >= 0
        AND actual_value NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric))))) NOT VALID""")
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        GRANT UPDATE (outcome,outcome_source,outcome_ref,outcome_observed_at,actual_value)
        ON analytics.predictions TO sportsbet_worker; END IF; END $$""")


def downgrade():
    op.execute('ALTER TABLE analytics.predictions DROP CONSTRAINT ck_prediction_settlement_evidence')
    op.execute('ALTER TABLE analytics.predictions DROP COLUMN actual_value,DROP COLUMN outcome_observed_at,DROP COLUMN outcome_ref,DROP COLUMN outcome_source')
