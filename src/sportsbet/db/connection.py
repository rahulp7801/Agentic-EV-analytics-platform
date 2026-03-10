"""Database connection factory for Quant-Sports platform.

Provides:
- get_sync_engine(): SQLAlchemy sync engine (psycopg v3) for bulk writes / Alembic
- create_async_pool(): asyncpg pool for low-latency runtime quant agent queries
"""

from __future__ import annotations

import asyncpg
import sqlalchemy as sa

from sportsbet.config import settings


def get_sync_engine() -> sa.Engine:
    """Return a SQLAlchemy sync engine using psycopg v3 driver.

    Used for bulk data writes (ingestion pipeline) and Alembic migrations.
    pool_pre_ping=True ensures stale connections are recycled automatically.
    """
    return sa.create_engine(settings.database_url, echo=False, pool_pre_ping=True)


async def create_async_pool(min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    """Return an asyncpg connection pool for runtime quant agent queries.

    asyncpg is used for async hot-path queries (Quant Agent, Arbitrage Agent)
    where sub-millisecond overhead matters.
    command_timeout=60 prevents runaway long queries from blocking the pool.
    """
    pool: asyncpg.Pool = await asyncpg.create_pool(
        settings.database_url_async,
        min_size=min_size,
        max_size=max_size,
        command_timeout=60,
    )
    return pool
