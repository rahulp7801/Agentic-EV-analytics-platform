"""Remove Supabase's default direct grants on application tables and the owner view."""
from alembic import op

revision = '0024_deny_browser_roles'
down_revision = '0023_worker_snapshot_append'
branch_labels = depends_on = None


def upgrade():
    op.execute('''DO $$ DECLARE
      target text;
      grantee text;
    BEGIN
      FOREACH target IN ARRAY ARRAY[
        'public.alembic_version','public.ev_signals','public.games','public.player_stats',
        'public.nba_player_gamelogs','public.nba_player_stats','public.play_by_play',
        'public.ngs_stats','public.injury_reports','public.odds_snapshots',
        'public.player_prop_snapshots','public.dashboard_snapshots','public.dashboard_gamelogs',
        'analytics.predictions','analytics.exposure','analytics.quotes','analytics.api_usage'
      ] LOOP
        EXECUTE format('REVOKE ALL ON %s FROM PUBLIC', target);
        FOREACH grantee IN ARRAY ARRAY['anon','authenticated'] LOOP
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=grantee) THEN
            EXECUTE format('REVOKE ALL ON %s FROM %I', target, grantee);
          END IF;
        END LOOP;
      END LOOP;
    END $$''')


def downgrade():
    # A schema rollback must not reopen direct browser access.
    pass
