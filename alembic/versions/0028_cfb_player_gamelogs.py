"""Add source-committed college-football player game logs."""
from alembic import op

revision = '0028_cfb_player_gamelogs'
down_revision = '0027_provider_response_cache'
branch_labels = depends_on = None

BASE_GAMELOG_VIEW = '''
    SELECT 'nba'::text AS sport, game_date, player_name, game_id AS game_key,
        jsonb_build_object('date',game_date,'player',player_name,
            'team',team_abbreviation,'opponent',opponent_team,'is_home',is_home,
            'points',points,'rebounds',rebounds,'assists',assists,'threes',threes_made,
            'steals',steals,'blocks',blocks,'minutes',minutes) AS payload
    FROM public.nba_player_gamelogs
    WHERE game_date IS NOT NULL AND player_name IS NOT NULL
    UNION ALL
    SELECT 'nfl',g.game_date,p.player_name,g.game_id,
        jsonb_build_object('date',g.game_date,'player',p.player_name,'team',p.team,
            'opponent',CASE WHEN p.team=g.home_team THEN g.away_team ELSE g.home_team END,
            'is_home',p.team=g.home_team,'pass_yds',p.passing_yards,'pass_tds',p.passing_tds,
            'rush_yds',p.rushing_yards,'rec_yds',p.receiving_yards,'receptions',p.receptions)
    FROM public.player_stats p
    JOIN LATERAL (
        SELECT MIN(game_date) AS game_date,MIN(game_id) AS game_id,
            MIN(home_team) AS home_team,MIN(away_team) AS away_team
        FROM public.games
        WHERE season=p.season AND week=p.week AND p.team IN (home_team,away_team)
        HAVING COUNT(*)=1
    ) g ON true
    WHERE p.player_name IS NOT NULL
'''

CFB_GAMELOG_VIEW = BASE_GAMELOG_VIEW + '''
    UNION ALL
    SELECT 'cfb',game_date,player_name,game_id,
        jsonb_build_object('date',game_date,'player',player_name,
            'team',team_abbreviation,'opponent',opponent_abbreviation,'is_home',is_home,
            'pass_yds',passing_yards,'rush_yds',rushing_yards,
            'rec_yds',receiving_yards,'receptions',receptions)
    FROM public.cfb_player_gamelogs
'''


def replace_gamelog_view(query: str):
    op.execute('CREATE OR REPLACE VIEW public.dashboard_gamelogs WITH (security_barrier=true) AS '+query)
    op.execute('REVOKE ALL ON public.dashboard_gamelogs FROM PUBLIC')
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
        REVOKE ALL ON public.dashboard_gamelogs FROM anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
        REVOKE ALL ON public.dashboard_gamelogs FROM authenticated;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_dashboard') THEN
        GRANT SELECT ON public.dashboard_gamelogs TO sportsbet_dashboard;
      END IF;
    END $$""")


def upgrade():
    op.execute('''CREATE TABLE cfb_player_gamelogs (
        id BIGSERIAL PRIMARY KEY,
        athlete_id BIGINT NOT NULL,
        game_id VARCHAR(20) NOT NULL,
        season SMALLINT NOT NULL,
        week SMALLINT NOT NULL,
        game_date DATE NOT NULL,
        player_name VARCHAR(100) NOT NULL,
        team_id BIGINT NOT NULL,
        team_name VARCHAR(100) NOT NULL,
        team_abbreviation VARCHAR(10) NOT NULL,
        opponent_id BIGINT NOT NULL,
        opponent_name VARCHAR(100) NOT NULL,
        opponent_abbreviation VARCHAR(10) NOT NULL,
        is_home BOOLEAN NOT NULL,
        passing_yards INTEGER,
        rushing_yards INTEGER,
        receiving_yards INTEGER,
        receptions SMALLINT,
        source_provider TEXT NOT NULL,
        source_sha256 VARCHAR(64) NOT NULL,
        source_player_sha256 VARCHAR(64) NOT NULL,
        source_schedule_sha256 VARCHAR(64) NOT NULL,
        source_record_sha256 VARCHAR(64) NOT NULL,
        source_observed_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_cfb_gamelog_player_game UNIQUE (athlete_id,game_id),
        CONSTRAINT ck_cfb_gamelog_evidence CHECK (
            season BETWEEN 2004 AND 2100 AND week BETWEEN 1 AND 25
            AND athlete_id > 0 AND team_id > 0 AND opponent_id > 0 AND team_id <> opponent_id
            AND BTRIM(player_name) <> '' AND BTRIM(team_name) <> ''
            AND BTRIM(team_abbreviation) <> '' AND BTRIM(opponent_name) <> ''
            AND BTRIM(opponent_abbreviation) <> ''
            AND receptions >= 0
            AND source_provider='sportsdataverse_espn'
            AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_player_sha256 ~ '^[0-9a-f]{64}$'
            AND source_schedule_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 ~ '^[0-9a-f]{64}$')
    )''')
    op.execute('CREATE INDEX idx_cfb_gamelog_athlete_date ON cfb_player_gamelogs (athlete_id,game_date DESC)')
    op.execute('CREATE INDEX idx_cfb_gamelog_team_week ON cfb_player_gamelogs (team_id,season,week)')
    op.execute('REVOKE ALL ON cfb_player_gamelogs FROM PUBLIC')
    op.execute('REVOKE ALL ON SEQUENCE cfb_player_gamelogs_id_seq FROM PUBLIC')
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
        EXECUTE 'REVOKE ALL ON cfb_player_gamelogs FROM anon';
        EXECUTE 'REVOKE ALL ON SEQUENCE cfb_player_gamelogs_id_seq FROM anon';
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
        EXECUTE 'REVOKE ALL ON cfb_player_gamelogs FROM authenticated';
        EXECUTE 'REVOKE ALL ON SEQUENCE cfb_player_gamelogs_id_seq FROM authenticated';
      END IF;
    END $$""")
    op.execute('ALTER TABLE cfb_player_gamelogs ENABLE ROW LEVEL SECURITY')
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE ON cfb_player_gamelogs TO sportsbet_worker';
        EXECUTE 'GRANT USAGE,SELECT ON SEQUENCE cfb_player_gamelogs_id_seq TO sportsbet_worker';
        EXECUTE 'CREATE POLICY sportsbet_worker_read ON cfb_player_gamelogs FOR SELECT TO sportsbet_worker USING (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_insert ON cfb_player_gamelogs FOR INSERT TO sportsbet_worker WITH CHECK (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_update ON cfb_player_gamelogs FOR UPDATE TO sportsbet_worker USING (true) WITH CHECK (true)';
      END IF; END $$""")
    replace_gamelog_view(CFB_GAMELOG_VIEW)
    op.execute('ALTER TABLE player_prop_snapshots DROP CONSTRAINT ck_player_prop_snapshots_complete_quote')
    op.execute('''ALTER TABLE player_prop_snapshots
        ADD CONSTRAINT ck_player_prop_snapshots_complete_quote CHECK (
            sport IN ('nba','nfl','cfb')
            AND game_id IS NOT NULL AND BTRIM(game_id) <> ''
            AND BTRIM(player_name) <> '' AND BTRIM(sportsbook) <> '' AND BTRIM(prop_type) <> ''
            AND line IS NOT NULL AND line >= 0
            AND price IS NOT NULL AND (price <= -100 OR price >= 100)
            AND implied_probability > 0 AND implied_probability < 1
            AND side IS NOT NULL AND side IN ('Over','Under')
            AND game_start_time IS NOT NULL AND snapped_at < game_start_time
        ) NOT VALID''')


def downgrade():
    op.execute('ALTER TABLE player_prop_snapshots DROP CONSTRAINT ck_player_prop_snapshots_complete_quote')
    op.execute('''ALTER TABLE player_prop_snapshots
        ADD CONSTRAINT ck_player_prop_snapshots_complete_quote CHECK (
            sport IN ('nba','nfl')
            AND game_id IS NOT NULL AND BTRIM(game_id) <> ''
            AND BTRIM(player_name) <> '' AND BTRIM(sportsbook) <> '' AND BTRIM(prop_type) <> ''
            AND line IS NOT NULL AND line >= 0
            AND price IS NOT NULL AND (price <= -100 OR price >= 100)
            AND implied_probability > 0 AND implied_probability < 1
            AND side IS NOT NULL AND side IN ('Over','Under')
            AND game_start_time IS NOT NULL AND snapped_at < game_start_time
        ) NOT VALID''')
    replace_gamelog_view(BASE_GAMELOG_VIEW)
    op.execute('DROP TABLE cfb_player_gamelogs')
