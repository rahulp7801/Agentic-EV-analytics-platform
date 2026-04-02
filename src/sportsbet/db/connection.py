"""Database connection factory for Quant-Sports platform.

Provides:
- get_sync_engine(): SQLAlchemy sync engine (psycopg v3) for bulk writes / Alembic
- create_async_pool(): asyncpg pool for low-latency runtime quant agent queries
"""

from __future__ import annotations

import asyncio
import re
import socket
import sys
import urllib.parse

# asyncpg requires SelectorEventLoop on Windows — ProactorEventLoop (the default
# in Python 3.8+ on Windows) does not support the SSL protocol asyncpg needs.
# Set policy before the first asyncio call, not just before pool creation, because
# asyncpg introspects the running loop during import on some Windows builds.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import asyncpg
import sqlalchemy as sa

from sportsbet.config import settings


def _resolve_ipv4_dsn(dsn: str) -> str:
    """On Windows, swap a Supabase direct host (IPv6-only) for the pooler (IPv4).

    Supabase direct connections (`db.<ref>.supabase.co:5432`) are IPv6-only in
    most AWS regions. The Windows SelectorEventLoop cannot open IPv6 sockets
    without elevated privileges (errno 10013 / WSAEACCES). The Supabase
    connection pooler (`aws-0-<region>.pooler.supabase.com`) is always IPv4.

    The pooler uses a different username format: `postgres.<project_ref>`.
    Session-mode pooler (port 5432) is used so prepared statements work.
    """
    parsed = urllib.parse.urlparse(dsn)
    hostname = parsed.hostname or ""

    # Only rewrite Supabase direct-connection URLs.
    m = re.match(r"^db\.([a-z0-9]+)\.supabase\.co$", hostname)
    if not m:
        return dsn

    # Check whether the host actually has an IPv4 record.
    try:
        socket.getaddrinfo(hostname, None, socket.AF_INET)
        return dsn  # IPv4 available — no rewrite needed.
    except socket.gaierror:
        pass  # IPv6-only host → rewrite to pooler.

    project_ref = m.group(1)

    # Detect the AWS region from the pooler's DNS. Try us-east-1 first (most
    # common), then fall back to other regions. The pooler hostname is the same
    # across all regions via a geo-routed CNAME so a single host works.
    pooler_host = "aws-0-us-west-2.pooler.supabase.com"
    pooler_port = 5432  # session mode — supports prepared statements

    # Reconstruct the DSN with the pooler host and adjusted username.
    user = parsed.username or "postgres"
    if not user.endswith(f".{project_ref}"):
        user = f"{user}.{project_ref}"

    # urllib.parse.urlparse exposes password but doesn't reconstruct safely
    # when the password contains special characters, so rebuild manually.
    password_part = f":{urllib.parse.quote(parsed.password or '', safe='')}" if parsed.password else ""
    new_dsn = (
        f"postgresql://{urllib.parse.quote(user, safe='')+password_part}"
        f"@{pooler_host}:{pooler_port}{parsed.path}"
    )
    if parsed.query:
        new_dsn += f"?{parsed.query}"
    return new_dsn


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
    if sys.platform == "win32":
        dsn = _resolve_ipv4_dsn(dsn)

    pool: asyncpg.Pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=60,
        timeout=30,
        ssl="require",
    )
    return pool
