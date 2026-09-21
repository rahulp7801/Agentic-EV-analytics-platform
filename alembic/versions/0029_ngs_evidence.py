"""Make NFL Next Gen Stats private, reproducible evidence."""
from alembic import op

revision = '0029_ngs_evidence'
down_revision = '0028_cfb_player_gamelogs'
branch_labels = depends_on = None


def upgrade():
    # Existing rows were written without a source commitment and the old writer
    # referenced columns the table did not have. NGS is free, reproducible source
    # data and is not used by the production probability model, so discard those
    # unverifiable rows before requiring provenance.
    op.execute('TRUNCATE TABLE ngs_stats')
    op.execute('''ALTER TABLE ngs_stats
        ADD COLUMN avg_intended_air_yards NUMERIC(6,3),
        ADD COLUMN passer_rating NUMERIC(6,2),
        ADD COLUMN attempts SMALLINT,
        ADD COLUMN avg_yac NUMERIC(6,3),
        ADD COLUMN catch_percentage NUMERIC(6,2),
        ADD COLUMN targets SMALLINT,
        ADD COLUMN receptions SMALLINT,
        ADD COLUMN percent_attempts_gte_eight_defenders NUMERIC(6,2),
        ADD COLUMN rush_attempts SMALLINT,
        ADD COLUMN source_provider VARCHAR(40) NOT NULL,
        ADD COLUMN source_url TEXT NOT NULL,
        ADD COLUMN source_sha256 VARCHAR(64) NOT NULL,
        ADD COLUMN source_record_sha256 VARCHAR(64) NOT NULL,
        ADD COLUMN source_observed_at TIMESTAMPTZ NOT NULL,
        ADD CONSTRAINT ck_ngs_evidence CHECK (
            season BETWEEN 2016 AND 2100 AND week BETWEEN 1 AND 22
            AND stat_type IN ('passing','receiving','rushing')
            AND player_gsis_id ~ '^00-[0-9]{7}$'
            AND team_abbr ~ '^[A-Z]{2,3}$'
            AND (player_position IS NULL OR player_position ~ '^[A-Z0-9/-]{1,5}$')
            AND ((stat_type = 'passing' AND avg_time_to_throw IS NOT NULL)
              OR (stat_type = 'receiving' AND avg_separation IS NOT NULL)
              OR (stat_type = 'rushing' AND efficiency IS NOT NULL))
            AND (attempts IS NULL OR attempts >= 0)
            AND (targets IS NULL OR targets >= 0)
            AND (receptions IS NULL OR receptions >= 0)
            AND (rush_attempts IS NULL OR rush_attempts >= 0)
            AND (aggressiveness IS NULL OR aggressiveness BETWEEN 0 AND 100)
            AND (catch_percentage IS NULL OR catch_percentage BETWEEN 0 AND 100)
            AND (percent_attempts_gte_eight_defenders IS NULL
              OR percent_attempts_gte_eight_defenders BETWEEN 0 AND 100)
            AND source_provider = 'nflverse_ngs'
            AND source_url ~ '^https://github[.]com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_(passing|receiving|rushing)[.]parquet$'
            AND source_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_sha256 ~ '^[0-9a-f]{64}$')
    ''')
    op.execute('REVOKE ALL ON ngs_stats FROM PUBLIC')
    op.execute('REVOKE ALL ON SEQUENCE ngs_stats_id_seq FROM PUBLIC')
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
        EXECUTE 'REVOKE ALL ON ngs_stats FROM anon';
        EXECUTE 'REVOKE ALL ON SEQUENCE ngs_stats_id_seq FROM anon';
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
        EXECUTE 'REVOKE ALL ON ngs_stats FROM authenticated';
        EXECUTE 'REVOKE ALL ON SEQUENCE ngs_stats_id_seq FROM authenticated';
      END IF;
    END $$""")
    op.execute('ALTER TABLE ngs_stats ENABLE ROW LEVEL SECURITY')
    # Role provisioning may already have installed the read policy before this
    # migration exists. Replace the complete worker policy set deterministically.
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_delete ON ngs_stats')
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_update ON ngs_stats')
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_insert ON ngs_stats')
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_read ON ngs_stats')
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON ngs_stats TO sportsbet_worker';
        EXECUTE 'GRANT USAGE,SELECT ON SEQUENCE ngs_stats_id_seq TO sportsbet_worker';
        EXECUTE 'CREATE POLICY sportsbet_worker_read ON ngs_stats FOR SELECT TO sportsbet_worker USING (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_insert ON ngs_stats FOR INSERT TO sportsbet_worker WITH CHECK (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_update ON ngs_stats FOR UPDATE TO sportsbet_worker USING (true) WITH CHECK (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_delete ON ngs_stats FOR DELETE TO sportsbet_worker USING (true)';
      END IF; END $$""")


def downgrade():
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_delete ON ngs_stats')
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_update ON ngs_stats')
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_insert ON ngs_stats')
    op.execute('DROP POLICY IF EXISTS sportsbet_worker_read ON ngs_stats')
    op.execute('ALTER TABLE ngs_stats DISABLE ROW LEVEL SECURITY')
    op.execute('''ALTER TABLE ngs_stats
        DROP CONSTRAINT ck_ngs_evidence,
        DROP COLUMN source_observed_at,
        DROP COLUMN source_record_sha256,
        DROP COLUMN source_sha256,
        DROP COLUMN source_url,
        DROP COLUMN source_provider,
        DROP COLUMN rush_attempts,
        DROP COLUMN percent_attempts_gte_eight_defenders,
        DROP COLUMN receptions,
        DROP COLUMN targets,
        DROP COLUMN catch_percentage,
        DROP COLUMN avg_yac,
        DROP COLUMN attempts,
        DROP COLUMN passer_rating,
        DROP COLUMN avg_intended_air_yards
    ''')
