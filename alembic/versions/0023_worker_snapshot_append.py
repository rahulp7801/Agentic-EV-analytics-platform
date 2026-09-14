"""Allow the restricted worker to append immutable provider quote evidence."""
from alembic import op


revision = '0023_worker_snapshot_append'
down_revision = '0022_worker_schema_policy'
branch_labels = depends_on = None


def upgrade():
    op.execute("""DO $$
    DECLARE sequence_name text;
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        GRANT INSERT ON public.odds_snapshots, public.player_prop_snapshots TO sportsbet_worker;

        DROP POLICY IF EXISTS sportsbet_worker_insert ON public.odds_snapshots;
        CREATE POLICY sportsbet_worker_insert ON public.odds_snapshots
          FOR INSERT TO sportsbet_worker WITH CHECK (true);
        DROP POLICY IF EXISTS sportsbet_worker_insert ON public.player_prop_snapshots;
        CREATE POLICY sportsbet_worker_insert ON public.player_prop_snapshots
          FOR INSERT TO sportsbet_worker WITH CHECK (true);

        FOREACH sequence_name IN ARRAY ARRAY[
          pg_get_serial_sequence('public.odds_snapshots', 'id'),
          pg_get_serial_sequence('public.player_prop_snapshots', 'id')
        ] LOOP
          IF sequence_name IS NOT NULL THEN
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO sportsbet_worker', sequence_name);
          END IF;
        END LOOP;
      END IF;
    END $$""")


def downgrade():
    op.execute("""DO $$
    DECLARE sequence_name text;
    BEGIN
      DROP POLICY IF EXISTS sportsbet_worker_insert ON public.odds_snapshots;
      DROP POLICY IF EXISTS sportsbet_worker_insert ON public.player_prop_snapshots;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        REVOKE INSERT ON public.odds_snapshots, public.player_prop_snapshots FROM sportsbet_worker;
        FOREACH sequence_name IN ARRAY ARRAY[
          pg_get_serial_sequence('public.odds_snapshots', 'id'),
          pg_get_serial_sequence('public.player_prop_snapshots', 'id')
        ] LOOP
          IF sequence_name IS NOT NULL THEN
            EXECUTE format('REVOKE USAGE, SELECT ON SEQUENCE %s FROM sportsbet_worker', sequence_name);
          END IF;
        END LOOP;
      END IF;
    END $$""")
