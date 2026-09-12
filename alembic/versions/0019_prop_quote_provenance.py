"""Require source commitments on every future player-prop quote."""
from alembic import op


revision = '0019_prop_quote_provenance'
down_revision = '0018_signed_stat_outcomes'
branch_labels = depends_on = None


def upgrade():
    op.execute('''
        ALTER TABLE player_prop_snapshots
        ADD COLUMN source_provider TEXT,
        ADD COLUMN source_sha256 VARCHAR(64),
        ADD COLUMN source_record_sha256 VARCHAR(64),
        ADD CONSTRAINT ck_player_prop_snapshots_source_evidence CHECK (
            source_provider IS NOT NULL AND source_provider = 'the_odds_api'
            AND source_sha256 IS NOT NULL AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 IS NOT NULL
            AND source_record_sha256 ~ '^[0-9a-f]{64}$'
        ) NOT VALID
    ''')


def downgrade():
    op.execute('''
        ALTER TABLE player_prop_snapshots
        DROP CONSTRAINT ck_player_prop_snapshots_source_evidence,
        DROP COLUMN source_record_sha256,
        DROP COLUMN source_sha256,
        DROP COLUMN source_provider
    ''')
