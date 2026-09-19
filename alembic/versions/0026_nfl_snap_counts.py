"""Add exact NFL player participation for injury-context evidence."""
from alembic import op

revision = '0026_nfl_snap_counts'
down_revision = '0025_deny_browser_defaults'
branch_labels = depends_on = None


def upgrade():
    op.execute('''CREATE TABLE nfl_snap_counts (
        id BIGSERIAL PRIMARY KEY,
        game_id VARCHAR(20) NOT NULL,
        season SMALLINT NOT NULL,
        week SMALLINT NOT NULL,
        player_name VARCHAR(100) NOT NULL,
        pfr_player_id VARCHAR(20) NOT NULL,
        position VARCHAR(5),
        team VARCHAR(3) NOT NULL,
        opponent VARCHAR(3) NOT NULL,
        offense_snaps SMALLINT NOT NULL,
        defense_snaps SMALLINT NOT NULL,
        source_provider TEXT NOT NULL,
        source_sha256 VARCHAR(64) NOT NULL,
        source_record_sha256 VARCHAR(64) NOT NULL,
        source_observed_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_nfl_snap_game_player UNIQUE (game_id,pfr_player_id),
        CONSTRAINT ck_nfl_snap_counts CHECK (
            season BETWEEN 2012 AND 2100 AND week BETWEEN 1 AND 25
            AND offense_snaps >= 0 AND defense_snaps >= 0
            AND source_provider='nflverse'
            AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 ~ '^[0-9a-f]{64}$')
    )''')
    op.execute('CREATE INDEX idx_nfl_snap_player_season ON nfl_snap_counts (pfr_player_id,season)')
    op.execute('CREATE INDEX idx_nfl_snap_team_week ON nfl_snap_counts (team,season,week)')
    # Migration owners can inherit permissive Supabase defaults. Close the new
    # evidence table before the application roles are provisioned or refreshed.
    op.execute('REVOKE ALL ON nfl_snap_counts FROM PUBLIC')
    op.execute('REVOKE ALL ON SEQUENCE nfl_snap_counts_id_seq FROM PUBLIC')
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
        EXECUTE 'REVOKE ALL ON nfl_snap_counts FROM anon';
        EXECUTE 'REVOKE ALL ON SEQUENCE nfl_snap_counts_id_seq FROM anon';
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
        EXECUTE 'REVOKE ALL ON nfl_snap_counts FROM authenticated';
        EXECUTE 'REVOKE ALL ON SEQUENCE nfl_snap_counts_id_seq FROM authenticated';
      END IF;
    END $$""")
    op.execute('ALTER TABLE nfl_snap_counts ENABLE ROW LEVEL SECURITY')
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE ON nfl_snap_counts TO sportsbet_worker';
        EXECUTE 'GRANT USAGE,SELECT ON SEQUENCE nfl_snap_counts_id_seq TO sportsbet_worker';
        EXECUTE 'CREATE POLICY sportsbet_worker_read ON nfl_snap_counts FOR SELECT TO sportsbet_worker USING (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_insert ON nfl_snap_counts FOR INSERT TO sportsbet_worker WITH CHECK (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_update ON nfl_snap_counts FOR UPDATE TO sportsbet_worker USING (true) WITH CHECK (true)';
      END IF; END $$""")


def downgrade():
    op.execute('DROP TABLE nfl_snap_counts')
