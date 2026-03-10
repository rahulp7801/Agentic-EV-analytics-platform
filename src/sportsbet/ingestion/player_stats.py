"""Player weekly stats ingestion module.

Loads weekly player statistics via nflreadpy.load_player_stats().
Applies a column whitelist (PLAYER_STATS_COLUMNS) and renames nflreadpy fields
to match the player_stats table schema where field names differ.

nflreadpy.load_player_stats() returns a Polars DataFrame.
"""
from __future__ import annotations

import gc

import polars as pl
import nflreadpy as nfl  # NOT nfl_data_py — archived Sep 2025
import sqlalchemy as sa
import structlog

from sportsbet.db.connection import get_sync_engine

log = structlog.get_logger()

# Column whitelist — matches player_stats ORM model columns (models.py).
# nflreadpy field names used here; renames applied via _COLUMN_RENAMES below.
PLAYER_STATS_COLUMNS: list[str] = [
    "player_id",
    "season",
    "week",
    "recent_team",   # renamed to 'team' to match schema
    "position",
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "fantasy_points_ppr",
]

# Map nflreadpy field names to our schema column names where they differ.
# 'recent_team' in nflreadpy -> 'team' in our player_stats table.
_COLUMN_RENAMES: dict[str, str] = {
    "recent_team": "team",
}


def ingest_player_stats_seasons(
    seasons: list[int], engine: sa.Engine | None = None
) -> None:
    """Load player weekly stats for the specified seasons.

    Applies column whitelist and renames nflreadpy fields to match the
    player_stats schema. Uses append+gc pattern consistent with pbp.py.

    Args:
        seasons: List of NFL season years to ingest.
        engine: SQLAlchemy sync engine. If None, creates from settings.
    """
    if engine is None:
        engine = get_sync_engine()

    for season in seasons:
        log.info("player_stats_load_start", season=season)

        df: pl.DataFrame = nfl.load_player_stats([season])

        # Available-only filter — prevents KeyError if a season lacks a column.
        available: list[str] = [c for c in PLAYER_STATS_COLUMNS if c in df.columns]
        df = df.select(available)

        # Rename nflreadpy fields to match our schema (only if present in df).
        rename_map = {k: v for k, v in _COLUMN_RENAMES.items() if k in df.columns}
        if rename_map:
            df = df.rename(rename_map)

        df.to_pandas().to_sql(
            "player_stats",
            engine,
            if_exists="append",
            index=False,
            chunksize=1000,
            method="multi",
        )

        del df
        gc.collect()

        log.info("player_stats_load_done", season=season)
