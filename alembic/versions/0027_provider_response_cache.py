"""Add a private shared provider-response cache with refresh leases."""
from alembic import op

revision = '0027_provider_response_cache'
down_revision = '0026_nfl_snap_counts'
branch_labels = depends_on = None


def upgrade():
    op.execute('''CREATE TABLE provider_response_cache (
        cache_key VARCHAR(255) PRIMARY KEY,
        provider VARCHAR(40) NOT NULL,
        sport VARCHAR(5) NOT NULL,
        payload JSONB,
        payload_sha256 VARCHAR(64),
        captured_at TIMESTAMPTZ,
        expires_at TIMESTAMPTZ,
        lease_owner VARCHAR(64),
        lease_until TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_provider_cache_identity CHECK (
            cache_key ~ '^[a-z0-9:_-]{1,255}$'
            AND provider='the_odds_api' AND sport IN ('nba','nfl','cfb')),
        CONSTRAINT ck_provider_cache_payload CHECK (
            (payload IS NULL AND payload_sha256 IS NULL AND captured_at IS NULL AND expires_at IS NULL)
            OR (payload IS NOT NULL AND payload_sha256 ~ '^[0-9a-f]{64}$'
                AND captured_at IS NOT NULL AND expires_at IS NOT NULL
                AND captured_at < expires_at AND expires_at <= captured_at + INTERVAL '24 hours')),
        CONSTRAINT ck_provider_cache_lease CHECK (
            (lease_owner IS NULL AND lease_until IS NULL)
            OR (lease_owner ~ '^[0-9a-f]{32}$' AND lease_until IS NOT NULL))
    )''')
    op.execute('CREATE INDEX idx_provider_cache_expiry ON provider_response_cache (expires_at)')
    op.execute('REVOKE ALL ON provider_response_cache FROM PUBLIC')
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
        EXECUTE 'REVOKE ALL ON provider_response_cache FROM anon';
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
        EXECUTE 'REVOKE ALL ON provider_response_cache FROM authenticated';
      END IF;
    END $$""")
    op.execute('ALTER TABLE provider_response_cache ENABLE ROW LEVEL SECURITY')
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sportsbet_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE ON provider_response_cache TO sportsbet_worker';
        EXECUTE 'CREATE POLICY sportsbet_worker_read ON provider_response_cache FOR SELECT TO sportsbet_worker USING (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_insert ON provider_response_cache FOR INSERT TO sportsbet_worker WITH CHECK (true)';
        EXECUTE 'CREATE POLICY sportsbet_worker_update ON provider_response_cache FOR UPDATE TO sportsbet_worker USING (true) WITH CHECK (true)';
      END IF; END $$""")


def downgrade():
    op.execute('DROP TABLE provider_response_cache')
