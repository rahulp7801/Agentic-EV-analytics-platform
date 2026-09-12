"""Reject NULL fields in newly written stat provenance."""
from alembic import op

revision = '0017_nonnull_stat_provenance'
down_revision = '0016_stat_source_provenance'
branch_labels = depends_on = None


def upgrade():
    op.execute("""ALTER TABLE player_stats DROP CONSTRAINT ck_player_stats_source_evidence,
        ADD CONSTRAINT ck_player_stats_source_evidence CHECK (
            source_provider IS NOT NULL AND source_provider='nflverse'
            AND source_sha256 IS NOT NULL AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 IS NOT NULL
            AND source_record_sha256 ~ '^[0-9a-f]{64}$'
            AND source_observed_at IS NOT NULL) NOT VALID""")
    op.execute("""ALTER TABLE nba_player_gamelogs DROP CONSTRAINT ck_nba_gamelog_source_evidence,
        ADD CONSTRAINT ck_nba_gamelog_source_evidence CHECK (
            source_provider IS NOT NULL AND source_provider IN ('nba','espn')
            AND source_sha256 IS NOT NULL AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 IS NOT NULL
            AND source_record_sha256 ~ '^[0-9a-f]{64}$'
            AND source_observed_at IS NOT NULL) NOT VALID""")


def downgrade():
    op.execute("""ALTER TABLE nba_player_gamelogs DROP CONSTRAINT ck_nba_gamelog_source_evidence,
        ADD CONSTRAINT ck_nba_gamelog_source_evidence CHECK (
            source_provider IN ('nba','espn') AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 ~ '^[0-9a-f]{64}$'
            AND source_observed_at IS NOT NULL) NOT VALID""")
    op.execute("""ALTER TABLE player_stats DROP CONSTRAINT ck_player_stats_source_evidence,
        ADD CONSTRAINT ck_player_stats_source_evidence CHECK (
            source_provider='nflverse' AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 ~ '^[0-9a-f]{64}$'
            AND source_observed_at IS NOT NULL) NOT VALID""")
