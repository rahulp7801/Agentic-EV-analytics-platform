"""Restricted hosted roles are verified against disposable PostgreSQL only."""
import os
import uuid

import psycopg
from psycopg import sql
import pytest
from sqlalchemy.engine import make_url

from sportsbet.db.access import READER, WORKER, provision_roles, role_url


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
        provision_roles(admin, passwords)
        admin.execute("INSERT INTO dashboard_snapshots(snapshot_key,payload) VALUES (%s,'{}')", (key,))
    try:
        with psycopg.connect(dsn, user=READER, password=passwords[READER], autocommit=True) as reader:
            assert reader.execute('SELECT count(*) FROM dashboard_snapshots WHERE snapshot_key=%s', (key,)).fetchone()[0] == 1
            assert reader.execute('SHOW default_transaction_read_only').fetchone()[0] == 'on'
            reader.execute('SELECT payload FROM dashboard_gamelogs LIMIT 1')
            reader.execute('SET default_transaction_read_only=off')
            for statement in ('DELETE FROM dashboard_snapshots WHERE false', 'SELECT * FROM analytics.predictions',
                              'SELECT * FROM nba_player_gamelogs',
                              'SELECT * FROM player_stats', 'CREATE TABLE public.forbidden_test(id int)'):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    reader.execute(statement)
        with psycopg.connect(dsn, user=WORKER, password=passwords[WORKER], autocommit=True) as worker:
            with worker.transaction(force_rollback=True):
                assert worker.execute("UPDATE dashboard_snapshots SET payload='{}' WHERE snapshot_key=%s", (key,)).rowcount == 1
                worker.execute('SELECT * FROM player_stats LIMIT 1')
                worker.execute('SELECT * FROM analytics.predictions LIMIT 1')
            for statement in ('DELETE FROM dashboard_snapshots WHERE false',
                              "UPDATE analytics.predictions SET payload='{}' WHERE false",
                              "UPDATE analytics.quotes SET probability=0 WHERE false"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    worker.execute(statement)
            assert worker.execute("SELECT has_column_privilege(current_user,'analytics.predictions','outcome','UPDATE')").fetchone()[0]
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
