"""Worker-only, shared cache for bounded provider responses."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from sportsbet.db.connection import get_sync_engine

MAX_PAYLOAD_BYTES = 4_000_000
MAX_TTL = timedelta(hours=24)
_KEY = re.compile(r'^[a-z0-9:_-]{1,255}$')
_OWNER = re.compile(r'^[a-f0-9]{32}$')


def payload_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValueError('Provider response exceeds cache limit')
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CachedResponse:
    payload: object
    captured_at: datetime
    expires_at: datetime


class ProviderResponseCache:
    """Coordinate provider reads across workers without exposing raw data to the web role."""

    def __init__(self, engine: Engine | None = None):
        self._engine = engine or get_sync_engine()
        self._owns_engine = engine is None

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    @staticmethod
    def _identity(key: str, provider: str, sport: str) -> None:
        if (not isinstance(key, str) or not _KEY.fullmatch(key)
                or provider != 'the_odds_api' or sport not in ('nba', 'nfl', 'cfb')):
            raise ValueError('Invalid provider cache identity')

    def load(self, key: str, provider: str, sport: str, now: datetime) -> CachedResponse | None:
        self._identity(key, provider, sport)
        if now.utcoffset() is None:
            raise ValueError('Cache time must be timezone-aware')
        with self._engine.connect() as conn:
            row = conn.execute(text('''SELECT payload,payload_sha256,captured_at,expires_at
                FROM provider_response_cache
                WHERE cache_key=:key AND provider=:provider AND sport=:sport
                  AND payload IS NOT NULL AND expires_at>:now'''),
                {'key': key, 'provider': provider, 'sport': sport, 'now': now}).mappings().one_or_none()
        if not row:
            return None
        try:
            if (row['captured_at'].utcoffset() is None or row['expires_at'].utcoffset() is None
                    or row['captured_at'] > now or row['expires_at'] <= now
                    or row['expires_at'] - row['captured_at'] > MAX_TTL
                    or payload_sha256(row['payload']) != row['payload_sha256']):
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        return CachedResponse(row['payload'], row['captured_at'], row['expires_at'])

    def claim(self, key: str, provider: str, sport: str, owner: str, now: datetime,
              lease: timedelta = timedelta(minutes=3)) -> bool:
        self._identity(key, provider, sport)
        if (not isinstance(owner, str) or not _OWNER.fullmatch(owner)
                or now.utcoffset() is None or not timedelta(0) < lease <= timedelta(minutes=5)):
            raise ValueError('Invalid provider cache lease')
        with self._engine.begin() as conn:
            row = conn.execute(text('''INSERT INTO provider_response_cache
                (cache_key,provider,sport,lease_owner,lease_until)
                VALUES (:key,:provider,:sport,:owner,:lease_until)
                ON CONFLICT (cache_key) DO UPDATE SET
                  provider=excluded.provider,sport=excluded.sport,
                  lease_owner=excluded.lease_owner,lease_until=excluded.lease_until,updated_at=NOW()
                WHERE provider_response_cache.lease_until IS NULL
                   OR provider_response_cache.lease_until<=:now
                RETURNING cache_key'''), {'key': key, 'provider': provider, 'sport': sport,
                    'owner': owner, 'now': now, 'lease_until': now + lease}).scalar_one_or_none()
        return row == key

    def store(self, key: str, provider: str, sport: str, owner: str, payload: object,
              captured_at: datetime, expires_at: datetime, release: bool = True) -> None:
        self._identity(key, provider, sport)
        if (not isinstance(owner, str) or not _OWNER.fullmatch(owner)
                or captured_at.utcoffset() is None or expires_at.utcoffset() is None
                or not captured_at < expires_at or expires_at - captured_at > MAX_TTL):
            raise ValueError('Invalid provider cache record')
        digest = payload_sha256(payload)
        lease_sql = ',lease_owner=NULL,lease_until=NULL' if release else ''
        with self._engine.begin() as conn:
            updated = conn.execute(text('''UPDATE provider_response_cache SET
                payload=CAST(:payload AS JSONB),payload_sha256=:digest,
                captured_at=:captured_at,expires_at=:expires_at,
                updated_at=NOW()''' + lease_sql + '''
                WHERE cache_key=:key AND provider=:provider AND sport=:sport
                  AND lease_owner=:owner'''), {'key': key, 'provider': provider, 'sport': sport,
                    'owner': owner, 'payload': json.dumps(payload, allow_nan=False),
                    'digest': digest, 'captured_at': captured_at, 'expires_at': expires_at}).rowcount
        if updated != 1:
            raise RuntimeError('Provider cache lease was lost')

    def release(self, key: str, provider: str, sport: str, owner: str) -> None:
        self._identity(key, provider, sport)
        if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
            raise ValueError('Invalid provider cache owner')
        with self._engine.begin() as conn:
            conn.execute(text('''UPDATE provider_response_cache
                SET lease_owner=NULL,lease_until=NULL,updated_at=NOW()
                WHERE cache_key=:key AND provider=:provider AND sport=:sport
                  AND lease_owner=:owner'''),
                {'key': key, 'provider': provider, 'sport': sport, 'owner': owner})
