"""Restricted hosted roles are verified against disposable PostgreSQL only."""
import os
import uuid

import psycopg
from psycopg import sql
import pytest
from sqlalchemy.engine import make_url

from sportsbet.db.access import (
    ANALYTICS_TABLES,
    APPEND_TABLES,
    CACHE_TABLES,
    READER,
    READ_TABLES,
    WORKER,
    provision_roles,
    role_url,
)


class _ExistingRolesConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        rendered = statement.as_string(None) if hasattr(statement, 'as_string') else statement
        self.statements.append((rendered, params))
        return self

    def fetchone(self):
        return (1,)


def test_provisioning_locks_policy_tables_before_reading_or_writing_role_catalogs():
    connection = _ExistingRolesConnection()

    with pytest.raises(ValueError, match='already exist'):
        provision_roles(connection, {READER: 'reader', WORKER: 'worker'})

    first_statement = connection.statements[0][0]
    assert first_statement.startswith('LOCK TABLE ')
    assert first_statement.endswith(' IN ACCESS EXCLUSIVE MODE')
    for table in ('alembic_version', *READ_TABLES, *APPEND_TABLES, *CACHE_TABLES, *ANALYTICS_TABLES):
        assert f'"{table}"' in first_statement
    assert connection.statements[1][0].startswith('SELECT 1 FROM pg_roles')


def test_role_urls_preserve_exact_provider_endpoint_and_escape_passwords():
    owner = 'postgresql+asyncpg://postgres.project:old@aws-1-us-east-1.pooler.supabase.com:5432/postgres?sslmode=verify-full'
    result = make_url(role_url(owner, WORKER, 'p@:/ss'))
    assert result.username == WORKER + '.project'
    assert result.password == 'p@:/ss'
    assert result.host == make_url(owner).host
    assert result.query == make_url(owner).query
    assert result.drivername == 'postgresql+asyncpg'


@pytest.mark.skipif(not os.environ.get('SPORTSBET_TEST_DATABASE_URL'), reason='Disposable database required')
def test_reader_cannot_write_or_read_audits_and_worker_cannot_rewrite_predictions():
    dsn = os.environ['SPORTSBET_TEST_DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://')
    passwords = {READER: uuid.uuid4().hex, WORKER: uuid.uuid4().hex}
    key = 'test-access-' + uuid.uuid4().hex
    with psycopg.connect(dsn) as admin:
        browser_roles_created = []
        for browser_role in ('anon', 'authenticated'):
            if not admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (browser_role,)).fetchone():
                admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(browser_role)))
                browser_roles_created.append(browser_role)
            # Reproduce Supabase defaults, including its owner-executed view.
            admin.execute(sql.SQL('GRANT ALL ON public.dashboard_snapshots, public.dashboard_gamelogs TO {}')
                          .format(sql.Identifier(browser_role)))
            for schema in ('public','analytics'):
                for kind in ('TABLES','SEQUENCES'):
                    admin.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT ALL ON {} TO {}')
                                  .format(sql.Identifier(schema),sql.SQL(kind),sql.Identifier(browser_role)))
        provision_roles(admin, passwords)
        for schema in ('public','analytics'):
            admin.execute(sql.SQL('CREATE TABLE {}(id SERIAL)').format(sql.Identifier(schema,'browser_provisioning_probe')))
            admin.execute(sql.SQL('CREATE VIEW {} AS SELECT * FROM {}').format(
                sql.Identifier(schema,'browser_provisioning_view'),sql.Identifier(schema,'browser_provisioning_probe')))
            for browser_role in ('anon','authenticated'):
                for name in ('browser_provisioning_probe','browser_provisioning_view'):
                    assert not admin.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                                             (browser_role,f'{schema}.{name}')).fetchone()[0]
                assert not admin.execute("SELECT has_sequence_privilege(%s,pg_get_serial_sequence(%s,'id'),'USAGE,SELECT,UPDATE')",
                                         (browser_role,f'{schema}.browser_provisioning_probe')).fetchone()[0]
            admin.execute(sql.SQL('DROP VIEW {}').format(sql.Identifier(schema,'browser_provisioning_view')))
            admin.execute(sql.SQL('DROP TABLE {}').format(sql.Identifier(schema,'browser_provisioning_probe')))
        admin.execute("INSERT INTO dashboard_snapshots(snapshot_key,payload) VALUES (%s,'{}')", (key,))
    try:
        with psycopg.connect(dsn, user=READER, password=passwords[READER], autocommit=True) as reader:
            for browser_role in ('anon', 'authenticated'):
                for table in ('public.dashboard_snapshots', 'public.dashboard_gamelogs',
                              'public.provider_response_cache'):
                    assert not reader.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                                              (browser_role, table)).fetchone()[0]
            assert reader.execute('SELECT count(*) FROM dashboard_snapshots WHERE snapshot_key=%s', (key,)).fetchone()[0] == 1
            assert reader.execute('SHOW default_transaction_read_only').fetchone()[0] == 'on'
            reader.execute('SELECT payload FROM dashboard_gamelogs LIMIT 1')
            reader.execute('SET default_transaction_read_only=off')
            for statement in ('DELETE FROM dashboard_snapshots WHERE false', 'SELECT * FROM analytics.predictions',
                              'SELECT * FROM nba_player_gamelogs',
                              'SELECT * FROM player_stats', 'SELECT * FROM provider_response_cache',
                              'CREATE TABLE public.forbidden_test(id int)'):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    reader.execute(statement)
        with psycopg.connect(dsn, user=WORKER, password=passwords[WORKER], autocommit=True) as worker:
            assert worker.execute('SELECT version_num FROM public.alembic_version').fetchone()[0]
            with worker.transaction(force_rollback=True):
                assert worker.execute("UPDATE dashboard_snapshots SET payload='{}' WHERE snapshot_key=%s", (key,)).rowcount == 1
                worker.execute('SELECT * FROM player_stats LIMIT 1')
                worker.execute('SELECT * FROM analytics.predictions LIMIT 1')
                assert worker.execute("""INSERT INTO player_prop_snapshots
                    (sport,game_id,player_name,sportsbook,prop_type,line,price,implied_probability,
                     snapped_at,side,game_start_time,source_provider,source_sha256,source_record_sha256)
                    VALUES ('nfl',%s,'Fixture','book','player_pass_yds',200.5,-110,0.523810,
                            NOW(),'Over',NOW()+INTERVAL '1 day','the_odds_api',%s,%s) RETURNING id""",
                    (key, 'a'*64, 'b'*64)).fetchone()[0]
                assert worker.execute("""INSERT INTO odds_snapshots
                    (sportsbook,market_type,line,price,outcome_name,game_start_time,snapped_at)
                    VALUES ('book','h2h',NULL,-110,'Fixture',NOW()+INTERVAL '1 day',NOW())
                    RETURNING id""").fetchone()[0]
                assert worker.execute("""INSERT INTO provider_response_cache
                    (cache_key,provider,sport,lease_owner,lease_until)
                    VALUES (%s,'the_odds_api','nfl',%s,NOW()+INTERVAL '1 minute')
                    RETURNING cache_key""", ('odds:event:nfl:test', 'a'*32)).fetchone()[0]
                assert worker.execute("""UPDATE provider_response_cache
                    SET lease_until=NOW()+INTERVAL '2 minutes'
                    WHERE cache_key='odds:event:nfl:test'""").rowcount == 1
                ngs_id = worker.execute("""INSERT INTO ngs_stats
                    (player_gsis_id,season,week,stat_type,team_abbr,player_position,
                     avg_time_to_throw,source_provider,source_url,source_sha256,
                     source_record_sha256,source_observed_at)
                    VALUES ('00-0000001',2026,1,'passing','SEA','QB',2.5,'nflverse_ngs',
                            'https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_passing.parquet',
                            %s,%s,NOW()) RETURNING id""", ('c'*64, 'd'*64)).fetchone()[0]
                assert worker.execute('UPDATE ngs_stats SET avg_time_to_throw=2.6 WHERE id=%s',
                                      (ngs_id,)).rowcount == 1
                assert worker.execute('DELETE FROM ngs_stats WHERE id=%s', (ngs_id,)).rowcount == 1
            for statement in ('DELETE FROM dashboard_snapshots WHERE false',
                              'UPDATE public.alembic_version SET version_num=version_num',
                              'UPDATE player_prop_snapshots SET line=line WHERE false',
                              'DELETE FROM player_prop_snapshots WHERE false',
                              'UPDATE odds_snapshots SET line=line WHERE false',
                              "UPDATE analytics.predictions SET payload='{}' WHERE false",
                              "UPDATE analytics.quotes SET probability=0 WHERE false"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    worker.execute(statement)
            for table in APPEND_TABLES:
                assert worker.execute('SELECT has_table_privilege(current_user,%s,\'INSERT\')',
                                      ('public.'+table,)).fetchone()[0]
                assert not worker.execute('SELECT has_table_privilege(current_user,%s,\'UPDATE,DELETE\')',
                                          ('public.'+table,)).fetchone()[0]
                assert worker.execute("SELECT has_sequence_privilege(current_user,"
                    "pg_get_serial_sequence(%s,'id'),'USAGE')", ('public.'+table,)).fetchone()[0]
            for table in CACHE_TABLES:
                assert worker.execute("SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE')",
                                      ('public.'+table,)).fetchone()[0]
                assert not worker.execute("SELECT has_table_privilege(current_user,%s,'DELETE,TRUNCATE')",
                                          ('public.'+table,)).fetchone()[0]
            assert worker.execute("SELECT has_table_privilege(current_user,'public.ngs_stats',"
                                  "'SELECT,INSERT,UPDATE,DELETE')").fetchone()[0]
            assert worker.execute("SELECT has_sequence_privilege(current_user,"
                                  "pg_get_serial_sequence('public.ngs_stats','id'),'USAGE')").fetchone()[0]
            for column in ('outcome','outcome_source','outcome_ref','outcome_observed_at','actual_value',
                           'outcome_evidence'):
                assert worker.execute("SELECT has_column_privilege(current_user,'analytics.predictions',%s,'UPDATE')",(column,)).fetchone()[0]
    finally:
        with psycopg.connect(dsn) as admin:
            admin.execute('DELETE FROM dashboard_snapshots WHERE snapshot_key=%s', (key,))
            policies = admin.execute("SELECT n.nspname,c.relname,p.polname FROM pg_policy p "
                "JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE p.polroles && ARRAY(SELECT oid FROM pg_roles WHERE rolname IN (%s,%s))", (READER,WORKER)).fetchall()
            for schema, table, policy in policies:
                admin.execute(sql.SQL('DROP POLICY {} ON {}').format(sql.Identifier(policy), sql.Identifier(schema,table)))
            for role in (READER, WORKER):
                admin.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            for role in browser_roles_created:
                admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
