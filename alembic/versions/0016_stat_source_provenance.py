"""Require source evidence on newly written NBA and NFL stat rows."""
from alembic import op

revision = '0016_stat_source_provenance'
down_revision = '0015_settlement_provenance'
branch_labels = depends_on = None


def upgrade():
    op.execute('ALTER TABLE nba_player_gamelogs ALTER COLUMN source_provider DROP DEFAULT')
    op.execute('ALTER TABLE player_stats ADD COLUMN source_provider TEXT, '
        'ADD COLUMN source_sha256 VARCHAR(64), ADD COLUMN source_record_sha256 VARCHAR(64), '
        'ADD COLUMN source_observed_at TIMESTAMPTZ')
    op.execute("""ALTER TABLE player_stats ADD CONSTRAINT ck_player_stats_source_evidence
        CHECK (source_provider='nflverse' AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 ~ '^[0-9a-f]{64}$' AND source_observed_at IS NOT NULL) NOT VALID""")
    op.execute('ALTER TABLE nba_player_gamelogs ADD COLUMN source_record_sha256 VARCHAR(64)')
    op.execute("""ALTER TABLE nba_player_gamelogs ADD CONSTRAINT ck_nba_gamelog_source_evidence
        CHECK (source_provider IN ('nba','espn') AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 ~ '^[0-9a-f]{64}$'
            AND source_observed_at IS NOT NULL) NOT VALID""")


def downgrade():
    op.execute('ALTER TABLE nba_player_gamelogs DROP CONSTRAINT ck_nba_gamelog_source_evidence, '
        'DROP COLUMN source_record_sha256')
    op.execute('ALTER TABLE player_stats DROP CONSTRAINT ck_player_stats_source_evidence, '
        'DROP COLUMN source_observed_at, DROP COLUMN source_record_sha256, '
        'DROP COLUMN source_sha256, DROP COLUMN source_provider')
    op.execute("ALTER TABLE nba_player_gamelogs ALTER COLUMN source_provider SET DEFAULT 'nba'")
