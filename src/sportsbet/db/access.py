"""Provision separate snapshot-reader and ingestion roles; never export owner credentials."""
from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from sportsbet.config import settings

READER = 'sportsbet_dashboard'
WORKER = 'sportsbet_worker'
READ_TABLES = ('games', 'player_stats', 'nfl_snap_counts', 'cfb_player_gamelogs', 'nba_player_gamelogs', 'nba_player_stats',
               'play_by_play', 'ngs_stats', 'injury_reports', 'odds_snapshots',
               'player_prop_snapshots', 'dashboard_snapshots')
WRITE_TABLES = ('games', 'player_stats', 'nfl_snap_counts', 'cfb_player_gamelogs', 'nba_player_gamelogs', 'dashboard_snapshots')
APPEND_TABLES = ('odds_snapshots', 'player_prop_snapshots')
CACHE_TABLES = ('provider_response_cache',)
ANALYTICS_TABLES = ('predictions', 'exposure', 'quotes', 'api_usage')


def deny_browser_roles(conn):
    """Supabase defaults can grant named browser roles independently of PUBLIC/RLS."""
    targets = [sql.Identifier('public', table) for table in
               (*READ_TABLES, *CACHE_TABLES, 'alembic_version', 'ev_signals', 'dashboard_gamelogs')]
    targets.extend(sql.Identifier('analytics', table) for table in ANALYTICS_TABLES)
    grantees = [sql.SQL('PUBLIC')]
    for role in ('anon', 'authenticated'):
        if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
            grantees.append(sql.Identifier(role))
    # Defaults belong to the connected application creator, not provider-admin roles.
    for schema in ('public', 'analytics'):
        for kind in ('TABLES', 'SEQUENCES'):
            conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL ON {} FROM {}').format(
                sql.Identifier(schema), sql.SQL(kind), sql.SQL(', ').join(grantees)))
    conn.execute(sql.SQL('REVOKE ALL ON {} FROM {}').format(
        sql.SQL(', ').join(targets), sql.SQL(', ').join(grantees)))


def _lock_policy_tables(conn):
    """Acquire policy-table locks before role/catalog writes can form a deadlock."""
    targets = [sql.Identifier('public', 'alembic_version')]
    targets.extend(sql.Identifier('public', table) for table in READ_TABLES)
    targets.extend(sql.Identifier('public', table) for table in CACHE_TABLES)
    targets.extend(sql.Identifier('analytics', table) for table in ANALYTICS_TABLES)
    conn.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(sql.SQL(', ').join(targets)))


def apply_access(conn):
    """Explicit grants and role-specific RLS policies; no rights for anonymous users."""
    deny_browser_roles(conn)
    conn.execute(sql.SQL('GRANT SELECT ON public.alembic_version TO {}').format(sql.Identifier(WORKER)))
    conn.execute('DROP POLICY IF EXISTS sportsbet_worker_schema_readiness ON public.alembic_version')
    conn.execute(sql.SQL('CREATE POLICY sportsbet_worker_schema_readiness ON public.alembic_version '
                         'FOR SELECT TO {} USING (true)').format(sql.Identifier(WORKER)))
    conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}, {}').format(sql.Identifier(READER), sql.Identifier(WORKER)))
    conn.execute(sql.SQL('GRANT SELECT ON public.dashboard_snapshots TO {}').format(sql.Identifier(READER)))
    conn.execute(sql.SQL('GRANT SELECT ON public.dashboard_gamelogs TO {}').format(sql.Identifier(READER)))
    for table in READ_TABLES:
        target = sql.Identifier('public', table)
        conn.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(target, sql.Identifier(WORKER)))
        conn.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(target))
        conn.execute(sql.SQL('DROP POLICY IF EXISTS sportsbet_worker_read ON {}').format(target))
        conn.execute(sql.SQL('CREATE POLICY sportsbet_worker_read ON {} FOR SELECT TO {} USING (true)').format(target, sql.Identifier(WORKER)))
    conn.execute('DROP POLICY IF EXISTS sportsbet_dashboard_read ON public.dashboard_snapshots')
    conn.execute(sql.SQL('CREATE POLICY sportsbet_dashboard_read ON public.dashboard_snapshots FOR SELECT TO {} USING (true)').format(sql.Identifier(READER)))
    for table in WRITE_TABLES:
        target = sql.Identifier('public', table)
        conn.execute(sql.SQL('GRANT INSERT, UPDATE ON {} TO {}').format(target, sql.Identifier(WORKER)))
        for command in ('INSERT', 'UPDATE'):
            policy = sql.Identifier('sportsbet_worker_' + command.lower())
            conn.execute(sql.SQL('DROP POLICY IF EXISTS {} ON {}').format(policy, target))
            clause = sql.SQL('WITH CHECK (true)' if command == 'INSERT' else 'USING (true) WITH CHECK (true)')
            conn.execute(sql.SQL('CREATE POLICY {} ON {} FOR {} TO {} {}').format(policy, target, sql.SQL(command), sql.Identifier(WORKER), clause))
    for table in APPEND_TABLES:
        target = sql.Identifier('public', table)
        conn.execute(sql.SQL('GRANT INSERT ON {} TO {}').format(target, sql.Identifier(WORKER)))
        conn.execute(sql.SQL('DROP POLICY IF EXISTS sportsbet_worker_insert ON {}').format(target))
        conn.execute(sql.SQL('CREATE POLICY sportsbet_worker_insert ON {} FOR INSERT TO {} WITH CHECK (true)')
                     .format(target, sql.Identifier(WORKER)))
    for table in CACHE_TABLES:
        target = sql.Identifier('public', table)
        conn.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON {} TO {}').format(target, sql.Identifier(WORKER)))
        conn.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(target))
        for command in ('SELECT', 'INSERT', 'UPDATE'):
            policy = sql.Identifier('sportsbet_worker_' + command.lower())
            conn.execute(sql.SQL('DROP POLICY IF EXISTS {} ON {}').format(policy, target))
            clause = sql.SQL('USING (true)' if command == 'SELECT' else
                'WITH CHECK (true)' if command == 'INSERT' else 'USING (true) WITH CHECK (true)')
            conn.execute(sql.SQL('CREATE POLICY {} ON {} FOR {} TO {} {}').format(
                policy, target, sql.SQL(command), sql.Identifier(WORKER), clause))
    conn.execute(sql.SQL('GRANT USAGE ON SCHEMA analytics TO {}').format(sql.Identifier(WORKER)))
    for table in ANALYTICS_TABLES:
        target = sql.Identifier('analytics', table)
        conn.execute(sql.SQL('GRANT SELECT, INSERT ON {} TO {}').format(target, sql.Identifier(WORKER)))
        conn.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(target))
        conn.execute(sql.SQL('DROP POLICY IF EXISTS sportsbet_worker_access ON {}').format(target))
        conn.execute(sql.SQL('CREATE POLICY sportsbet_worker_access ON {} TO {} USING (true) WITH CHECK (true)').format(target, sql.Identifier(WORKER)))
    conn.execute(sql.SQL('GRANT UPDATE (outcome,outcome_source,outcome_ref,outcome_observed_at,actual_value,outcome_evidence) ON analytics.predictions TO {}').format(sql.Identifier(WORKER)))
    for table in ('exposure', 'api_usage'):
        conn.execute(sql.SQL('GRANT UPDATE ON {} TO {}').format(sql.Identifier('analytics', table), sql.Identifier(WORKER)))
    # Only sequences attached to writable public tables, not every current/future sequence.
    for table in (*WRITE_TABLES, *APPEND_TABLES):
        rows = conn.execute("SELECT pg_get_serial_sequence(%s, column_name) FROM information_schema.columns "
                            "WHERE table_schema='public' AND table_name=%s", (f'public.{table}', table)).fetchall()
        for (sequence,) in rows:
            if sequence:
                schema, name = sequence.split('.', 1)
                conn.execute(sql.SQL('GRANT USAGE, SELECT ON SEQUENCE {} TO {}').format(sql.Identifier(schema, name), sql.Identifier(WORKER)))


def provision_roles(conn, passwords: dict[str, str]):
    # RLS policy DDL needs ACCESS EXCLUSIVE locks. Take every required lock before
    # CREATE ROLE writes the system catalogs, otherwise autovacuum can deadlock
    # while it waits on this transaction and this transaction waits on its table.
    _lock_policy_tables(conn)
    for role in (READER, WORKER):
        if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
            raise ValueError('Application roles already exist; refuse implicit credential rotation')
        conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE '
                             'NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 12 PASSWORD {}')
                     .format(sql.Identifier(role), sql.Literal(passwords[role])))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='60s'").format(sql.Identifier(role)))
        conn.execute(sql.SQL("ALTER ROLE {} SET lock_timeout='5s'").format(sql.Identifier(role)))
    conn.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only=on').format(sql.Identifier(READER)))
    conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='5s'").format(sql.Identifier(READER)))
    apply_access(conn)


def role_url(owner_url: str, role: str, password: str) -> str:
    url = make_url(owner_url)
    username = role
    if url.host and url.host.endswith('.pooler.supabase.com'):
        if not url.username or '.' not in url.username:
            raise ValueError('Supabase shared pooler requires the exact project-qualified username')
        username += '.' + url.username.split('.', 1)[1]
    return url.set(username=username, password=password).render_as_string(hide_password=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials-file', type=Path, default=Path('.local/secrets/hosted-database.json'))
    args = parser.parse_args()
    try:
        if args.credentials_file.exists():
            raise ValueError('Credential file already exists; refuse to overwrite it')
        args.credentials_file.parent.mkdir(parents=True, exist_ok=True)
        passwords = {role: secrets.token_urlsafe(36) for role in (READER, WORKER)}
        credentials = {role: dict(password=password, database_url=role_url(settings.database_url, role, password),
            database_url_async=role_url(settings.database_url_async, role, password)) for role, password in passwords.items()}
        # Write exclusively before provisioning so credentials survive interruption.
        with args.credentials_file.open('x', encoding='utf-8') as handle:
            json.dump(credentials, handle, indent=2)
        with psycopg.connect(settings.database_url.replace('postgresql+psycopg://','postgresql://'), connect_timeout=15) as conn:
            provision_roles(conn, passwords)
        print('Restricted database roles created. Credentials saved locally; no owner credential exported.')
    except Exception as exc:
        raise SystemExit(f'Role provisioning failed ({type(exc).__name__}); inspect local setup state before retrying.') from None


if __name__ == '__main__':
    main()
