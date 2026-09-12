"""Allow finite signed actual values for NFL stat settlements."""
from alembic import op

revision = '0018_signed_stat_outcomes'
down_revision = '0017_nonnull_stat_provenance'
branch_labels = depends_on = None


def upgrade():
    op.execute("""ALTER TABLE analytics.predictions
        DROP CONSTRAINT ck_prediction_settlement_evidence,
        ADD CONSTRAINT ck_prediction_settlement_evidence CHECK (
            (actual_value IS NULL OR actual_value NOT IN
                ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric))
            AND (outcome IS NULL OR (outcome IN
                ('true','false','\"push\"','\"void\"','null')
                AND LENGTH(outcome_source) BETWEEN 1 AND 40
                AND LENGTH(outcome_ref) BETWEEN 1 AND 200
                AND outcome_observed_at IS NOT NULL))) NOT VALID""")


def downgrade():
    op.execute("""ALTER TABLE analytics.predictions
        DROP CONSTRAINT ck_prediction_settlement_evidence,
        ADD CONSTRAINT ck_prediction_settlement_evidence CHECK (
            outcome IS NULL OR (outcome IN
                ('true','false','\"push\"','\"void\"','null')
                AND LENGTH(outcome_source) BETWEEN 1 AND 40
                AND LENGTH(outcome_ref) BETWEEN 1 AND 200
                AND outcome_observed_at IS NOT NULL
                AND (actual_value IS NULL OR (actual_value >= 0 AND actual_value NOT IN
                    ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric))))) NOT VALID""")
