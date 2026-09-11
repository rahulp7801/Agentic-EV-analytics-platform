"""Track NBA stat provenance so fallback data cannot replace official records."""
from alembic import op

revision = '0013_nba_stat_provenance'
down_revision = '0012_dashboard_game_logs'
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE nba_player_gamelogs ADD COLUMN source_provider TEXT NOT NULL DEFAULT 'nba' CHECK (source_provider IN ('nba','espn'))")
    op.execute('ALTER TABLE nba_player_gamelogs ADD COLUMN source_sha256 VARCHAR(64)')
    op.execute('ALTER TABLE nba_player_gamelogs ADD COLUMN source_observed_at TIMESTAMPTZ')


def downgrade():
    op.execute('ALTER TABLE nba_player_gamelogs DROP COLUMN source_observed_at, DROP COLUMN source_sha256, DROP COLUMN source_provider')
