"""Database connection factory for Quant-Sports platform.

Provides:
- get_sync_engine(): SQLAlchemy sync engine (psycopg v3) for bulk writes / Alembic
- create_async_pool(): asyncpg pool for low-latency runtime quant agent queries
"""

from __future__ import annotations

import asyncio
import sys

# asyncpg requires SelectorEventLoop on Windows — ProactorEventLoop (the default
# in Python 3.8+ on Windows) does not support the SSL protocol asyncpg needs.
# Set policy before the first asyncio call, not just before pool creation, because
# asyncpg introspects the running loop during import on some Windows builds.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import asyncpg
import sqlalchemy as sa

from sportsbet.config import settings


def get_sync_engine() -> sa.Engine:
    """Return a SQLAlchemy sync engine using psycopg v3 driver.

    Used for bulk data writes (ingestion pipeline) and Alembic migrations.
    pool_pre_ping=True ensures stale connections are recycled automatically.
    """
    return sa.create_engine(settings.database_url, echo=False, pool_pre_ping=True)


async def create_async_pool(min_size: int = 0, max_size: int = 10) -> asyncpg.Pool:
    """Return an asyncpg connection pool for runtime quant agent queries.

    asyncpg is used for async hot-path queries (Quant Agent, Arbitrage Agent)
    where sub-millisecond overhead matters.
    command_timeout=60 prevents runaway long queries from blocking the pool.

    min_size=0: pool starts empty — connections created lazily on first acquire().
        The old default of 2 caused 5-minute hangs on cold starts because asyncpg's
        default per-connection timeout is 300s. With min_size=0, create_pool() returns
        immediately; any unreachable-DB error surfaces at the first query instead.
    timeout=30: per-connection attempt timeout. Accommodates Supabase cold starts
        (~10-20s to wake) while still failing fast instead of waiting the default 300s.
    """
    dsn = settings.database_url_async.replace("postgresql+asyncpg://", "postgresql://")
    pool: asyncpg.Pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=60,
        timeout=30,
        ssl="require",
    )
    return pool
