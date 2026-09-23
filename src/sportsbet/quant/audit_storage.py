"""Explicit hosted-ledger access for read-only, consistent evaluation snapshots."""
from __future__ import annotations

from contextlib import contextmanager
import os

from sportsbet.ledger import Ledger


def audit_database_url(environment: str | None = None) -> str:
    """A missing explicit source must never fall back to a local ledger."""
    names=(environment,) if environment is not None else ('ANALYTICS_DATABASE_URL','DATABASE_URL')
    for name in names:
        value=os.environ.get(name)
        if value and value.strip():
            if not value.startswith(('postgresql://','postgres://','postgresql+psycopg://')):
                raise ValueError('Audit source must be a PostgreSQL database URL')
            return value
    raise ValueError('Configure the requested hosted audit database environment variable')


class ReadOnlyLedger(Ledger):
    def __init__(self, *, database_url: str):
        if not isinstance(database_url,str) or not database_url.startswith(
                ('postgresql://','postgres://','postgresql+psycopg://')):
            raise ValueError('A hosted PostgreSQL audit source is required')
        self.database_url=database_url
        self._session=None

    @contextmanager
    def _open_session(self):
        import psycopg
        with psycopg.connect(self.database_url.replace('postgresql+psycopg://','postgresql://',1),
                connect_timeout=15,options='-c default_transaction_read_only=on -c statement_timeout=120000 '
                '-c idle_in_transaction_session_timeout=60000') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.execute('SET LOCAL search_path TO analytics, public')
            conn.execute("SET LOCAL application_name='sportsbet_evidence_audit'")
            class Session:
                def execute(self,sql,args=()):
                    return conn.execute(sql.replace('?', '%s'),args)
                def executemany(self,sql,args):
                    with conn.cursor() as cursor:
                        cursor.executemany(sql.replace('?', '%s'),args)
            yield Session()

    @contextmanager
    def connect(self):
        if self._session is not None:
            yield self._session
        else:
            with self._open_session() as session:
                yield session

    @contextmanager
    def snapshot(self):
        """Keep forecasts, settlement state and closing quotes in one snapshot."""
        if self._session is not None:
            raise RuntimeError('Audit snapshots cannot be nested')
        with self._open_session() as session:
            self._session=session
            try:
                yield self
            finally:
                self._session=None
