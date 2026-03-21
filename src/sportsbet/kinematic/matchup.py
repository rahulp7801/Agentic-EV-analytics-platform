"""Kinematic matchup query executor — run_matchup_query async function.

Executes the NGS separation query for a given receiver/season and produces
a KinematicAnalysis with geometric mismatch signal.

SEPARATION_THRESHOLD is documented as configurable (Settings.kinematic_separation_threshold
in a future phase). For v1, it is hardcoded at the module level.

Security chain:
  KinematicParams (Pydantic validated) -> _SEPARATION_QUERY ($1/$2 params) -> asyncpg
  Column names NEVER come from user input — _SEPARATION_QUERY is a hardcoded string.

Pitfall guards (from RESEARCH.md):
- Pitfall 1: press_man_rate is ALWAYS None — do not query it.
- Pitfall 3: Decimal(str(row["field"])) wrapping for asyncpg NUMERIC columns.

No imports from graph/ — one-way dependency enforced.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import asyncpg
import structlog

from sportsbet.kinematic.models import KinematicAnalysis, KinematicParams

log = structlog.get_logger()

# Configurable mismatch threshold. Elite separation is ~>= 2.5 yards.
# Documented as a heuristic starting point — calibrate against historical outcome data.
SEPARATION_THRESHOLD: Decimal = Decimal("2.5")

# Parameterized NGS receiving query — column names are hardcoded, values are $N params.
_SEPARATION_QUERY = """
    SELECT
        player_gsis_id,
        season,
        AVG(avg_separation) AS season_avg_separation,
        AVG(avg_cushion)    AS season_avg_cushion,
        COUNT(*)            AS weeks_sampled
    FROM ngs_stats
    WHERE player_gsis_id = $1
      AND season = $2
      AND stat_type = 'receiving'
      AND avg_separation IS NOT NULL
    GROUP BY player_gsis_id, season
"""


async def run_matchup_query(pool: asyncpg.Pool, params: KinematicParams) -> KinematicAnalysis:
    """Execute NGS separation query and return a KinematicAnalysis.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    params:
        KinematicParams — must be Pydantic-validated before this call.

    Returns
    -------
    KinematicAnalysis
        - ngs_available=True, all Decimal fields populated if row exists
        - ngs_available=True, all Decimal fields=None if row is empty (not an error)
        - geometric_mismatch_flag=True if avg_separation >= SEPARATION_THRESHOLD
        - press_man_rate=None always

    Notes
    -----
    asyncpg returns Decimal natively for NUMERIC columns. Explicit
    Decimal(str(value)) wrapping is applied per RESEARCH.md Pitfall 3.
    """
    log.info(
        "kinematic_matchup_query_executing",
        receiver_gsis_id=params.receiver_gsis_id,
        season=params.season,
        week=params.week,
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(_SEPARATION_QUERY, params.receiver_gsis_id, params.season)

    # No data for this receiver/season — return with all Decimal fields=None
    if row is None or row["weeks_sampled"] is None:
        log.info(
            "kinematic_no_data_for_receiver",
            receiver_gsis_id=params.receiver_gsis_id,
            season=params.season,
        )
        return KinematicAnalysis(
            season=params.season,
            week=params.week,
            receiver_gsis_id=params.receiver_gsis_id,
            ngs_available=True,
            geometric_mismatch_flag=False,
            press_man_rate=None,
        )

    # Wrap asyncpg NUMERIC columns with Decimal(str(...)) — RESEARCH.md Pitfall 3
    avg_sep: Optional[Decimal] = (
        Decimal(str(row["season_avg_separation"]))
        if row["season_avg_separation"] is not None
        else None
    )
    avg_cush: Optional[Decimal] = (
        Decimal(str(row["season_avg_cushion"]))
        if row["season_avg_cushion"] is not None
        else None
    )
    avg_ttt: Optional[Decimal] = (
        Decimal(str(row["avg_time_to_throw"]))
        if row.get("avg_time_to_throw") is not None
        else None
    )

    # Compute geometric mismatch flag from threshold
    mismatch_flag: bool = avg_sep is not None and avg_sep >= SEPARATION_THRESHOLD

    # Build signal description only when flag is set
    signal_desc: Optional[str] = None
    if mismatch_flag and avg_sep is not None:
        signal_desc = (
            f"High-separation receiver (avg sep {avg_sep:.2f}yd) — geometric mismatch flag"
        )

    log.info(
        "kinematic_analysis_computed",
        receiver_gsis_id=params.receiver_gsis_id,
        season=params.season,
        avg_separation=str(avg_sep),
        geometric_mismatch_flag=mismatch_flag,
    )

    return KinematicAnalysis(
        season=params.season,
        week=params.week,
        receiver_gsis_id=params.receiver_gsis_id,
        avg_separation=avg_sep,
        avg_cushion=avg_cush,
        avg_time_to_throw=avg_ttt,
        press_man_rate=None,   # ALWAYS None — forward-compat placeholder
        geometric_mismatch_flag=mismatch_flag,
        signal_description=signal_desc,
        ngs_available=True,
    )
