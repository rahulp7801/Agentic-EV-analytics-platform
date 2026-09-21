"""Pregame-only NFL Next Gen Stats context for published forecasts."""
from __future__ import annotations

from datetime import date, datetime
import math
import re

import asyncpg

METRICS = {
    "passing": (
        "avg_time_to_throw", "avg_completed_air_yards", "avg_intended_air_yards",
        "aggressiveness",
    ),
    "receiving": (
        "avg_separation", "avg_cushion", "avg_yac_above_expectation",
    ),
    "rushing": (
        "efficiency", "percent_attempts_gte_eight_defenders",
        "rush_yards_over_expected", "avg_time_to_los",
    ),
}
PROP_STAT_TYPE = {
    "pass_yds": "passing",
    "pass_tds": "passing",
    "rush_yds": "rushing",
    "rec_yds": "receiving",
    "receptions": "receiving",
}
TEAM_ALIASES = {"LAR": "LA", "WSH": "WAS"}
MAX_SAMPLE_WEEKS = 8

_EVIDENCE_QUERY = """
    WITH prior AS (
        SELECT * FROM ngs_stats
        WHERE player_gsis_id=$1 AND stat_type=$2
          AND season >= $3-1
          AND (season < $3 OR (season=$3 AND week < $4))
          AND week >= 1
        ORDER BY season DESC,week DESC
        LIMIT 8
    )
    SELECT COUNT(*) AS sample_weeks,
           AVG(avg_time_to_throw) AS avg_time_to_throw,
           AVG(avg_completed_air_yards) AS avg_completed_air_yards,
           AVG(avg_intended_air_yards) AS avg_intended_air_yards,
           AVG(aggressiveness) AS aggressiveness,
           AVG(avg_separation) AS avg_separation,
           AVG(avg_cushion) AS avg_cushion,
           AVG(avg_yac_above_expectation) AS avg_yac_above_expectation,
           AVG(efficiency) AS efficiency,
           AVG(percent_attempts_gte_eight_defenders) AS percent_attempts_gte_eight_defenders,
           AVG(rush_yards_over_expected) AS rush_yards_over_expected,
           AVG(avg_time_to_los) AS avg_time_to_los,
           MAX(source_provider) AS source_provider,
           MAX(source_url) AS source_url,
           MAX(source_sha256) AS source_sha256,
           MAX(source_observed_at) AS source_observed_at,
           COUNT(DISTINCT source_provider) AS source_provider_count,
           COUNT(DISTINCT source_url) AS source_url_count,
           COUNT(DISTINCT source_sha256) AS source_version_count
    FROM prior
"""


async def load_ngs_evidence(
    pool: asyncpg.Pool,
    *,
    player_gsis_id: str,
    season: int,
    game_date: date,
    team: str,
    prop_type: str,
) -> dict | None:
    """Return prior weekly tracking context without modifying model probability."""
    stat_type = PROP_STAT_TYPE.get(prop_type)
    if (
        stat_type is None
        or re.fullmatch(r"00-[0-9]{7}", player_gsis_id) is None
        or not 2016 <= season <= 2100
        or re.fullmatch(r"[A-Z]{2,3}", team) is None
        or type(game_date) is not date
    ):
        return None
    team = TEAM_ALIASES.get(team, team)
    metrics = METRICS[stat_type]
    async with pool.acquire() as conn:
        games = await conn.fetch(
            """SELECT week FROM games
               WHERE season=$1 AND game_date=$2
                 AND (home_team=$3 OR away_team=$3)
               ORDER BY game_id LIMIT 2""",
            season, game_date, team,
        )
        if len(games) != 1:
            return None
        try:
            cutoff_week = games[0]["week"]
        except (KeyError, TypeError):
            return None
        if type(cutoff_week) is not int or not 1 <= cutoff_week <= 22:
            return None
        row = await conn.fetchrow(
            _EVIDENCE_QUERY, player_gsis_id, stat_type, season, cutoff_week
        )
    if row is None or not row["sample_weeks"]:
        return None
    expected_url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"nextgen_stats/ngs_{stat_type}.parquet"
    )
    if (
        row["source_provider_count"] != 1
        or row["source_url_count"] != 1
        or row["source_version_count"] != 1
        or row["source_provider"] != "nflverse_ngs"
        or row["source_url"] != expected_url
        or not isinstance(row["source_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]) is None
        or not isinstance(row["source_observed_at"], datetime)
        or row["source_observed_at"].utcoffset() is None
    ):
        return None
    values = {
        column: float(row[column])
        for column in metrics
        if row[column] is not None
    }
    if not values or any(not math.isfinite(value) for value in values.values()):
        return None
    return {
        "status": "observed",
        "stat_type": stat_type,
        "sample_weeks": int(row["sample_weeks"]),
        "cutoff_season": season,
        "cutoff_week": cutoff_week,
        "cutoff_exclusive": True,
        "metrics": values,
        "source_provider": row["source_provider"],
        "source_url": row["source_url"],
        "source_sha256": row["source_sha256"],
        "source_observed_at": row["source_observed_at"].isoformat(),
        "probability_adjusted": False,
    }
