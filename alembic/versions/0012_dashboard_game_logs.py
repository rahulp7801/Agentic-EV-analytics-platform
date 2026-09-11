"""Expose only public game-log fields to the restricted dashboard reader."""
from alembic import op

revision = '0012_dashboard_game_logs'
down_revision = '0011_player_names_and_budget'
branch_labels = depends_on = None


def upgrade():
    op.execute('''
        CREATE VIEW public.dashboard_gamelogs WITH (security_barrier=true) AS
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
    ''')
    # This view intentionally exposes public stats, never raw tables or audit records.
    op.execute('REVOKE ALL ON public.dashboard_gamelogs FROM PUBLIC')
    op.execute('''DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_dashboard') THEN
            GRANT SELECT ON public.dashboard_gamelogs TO sportsbet_dashboard;
        END IF;
    END $$''')


def downgrade():
    op.execute('DROP VIEW public.dashboard_gamelogs')
