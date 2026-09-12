"""Reject new incomplete player-prop quotes while retaining legacy evidence."""
from alembic import op


revision = '0014_prop_snapshot_integrity'
down_revision = '0013_nba_stat_provenance'
branch_labels = depends_on = None


def upgrade():
    op.execute('''
        ALTER TABLE player_prop_snapshots
        ADD CONSTRAINT ck_player_prop_snapshots_complete_quote CHECK (
            sport IN ('nba', 'nfl')
            AND game_id IS NOT NULL AND BTRIM(game_id) <> ''
            AND BTRIM(player_name) <> ''
            AND BTRIM(sportsbook) <> ''
            AND BTRIM(prop_type) <> ''
            AND line IS NOT NULL AND line >= 0
            AND price IS NOT NULL AND (price <= -100 OR price >= 100)
            AND implied_probability > 0 AND implied_probability < 1
            AND side IS NOT NULL AND side IN ('Over', 'Under')
            AND game_start_time IS NOT NULL
            AND snapped_at < game_start_time
        ) NOT VALID
    ''')


def downgrade():
    op.execute('''
        ALTER TABLE player_prop_snapshots
        DROP CONSTRAINT ck_player_prop_snapshots_complete_quote
    ''')
