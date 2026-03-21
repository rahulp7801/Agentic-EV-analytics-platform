"""NGS season availability guard for the Kinematic Agent.

check_ngs_availability queries ngs_stats to confirm the requested season has
non-null avg_separation rows before any matchup query executes.

This is KINE-03: if the season has zero eligible rows, the Kinematic Agent
returns KinematicAnalysis with None fields rather than raising or returning
zeros. The guard prevents misleading "empty result" analysis.

No imports from graph/ — one-way dependency enforced.
"""
from __future__ import annotations

import asyncpg


async def check_ngs_availability(pool: asyncpg.Pool, season: int) -> bool:
    """Return True if ngs_stats has receiving rows with avg_separation for the season.

    Query: COUNT(*) of ngs_stats rows where stat_type='receiving' and avg_separation
    is not null for the given season. A count > 0 means NGS data is available.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    season:
        NFL season year to check (e.g. 2024).

    Returns
    -------
    bool
        True if at least one row exists, False otherwise.
        Returns False (not raises) for seasons with no data.
    """
    sql = """
        SELECT COUNT(*) AS n
        FROM ngs_stats
        WHERE season = $1
          AND stat_type = 'receiving'
          AND avg_separation IS NOT NULL
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, season)
    return int(row["n"]) > 0
