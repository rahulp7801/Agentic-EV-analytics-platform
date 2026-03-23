"""Play-by-play ingestion module.

Loads NFL PBP data year-by-year using nflreadpy (NOT nfl_data_py — archived Sep 2025).
Uses a column whitelist to prevent memory bloat from nflreadpy's ~400-column full schema.
Enforces a memory guard to abort early if system memory exceeds 80% before a season load.

Pattern from RESEARCH.md Pattern 2: year-by-year loop with gc.collect() between seasons.
"""
from __future__ import annotations

import gc

import psutil
import sqlalchemy as sa
import structlog

from sportsbet.db.connection import get_sync_engine

log = structlog.get_logger()

# Column whitelist — only columns queried by downstream quant agents.
# Source: RESEARCH.md Pattern 2, ARCHITECTURE.md schema.
# Exactly 21 columns: verified by test_pbp_columns_count.
PBP_COLUMNS: list[str] = [
    "game_id",
    "play_id",
    "season",
    "week",
    "posteam",
    "defteam",
    "play_type",
    "yards_gained",
    "down",
    "ydstogo",
    "passer_player_id",
    "receiver_player_id",
    "rusher_player_id",
    "pass_touchdown",
    "rush_touchdown",
    "interception",
    "epa",
    "wp",
    "air_yards",
    "two_point_attempt",
    "complete_pass",
]


def ingest_pbp_seasons(seasons: list[int], engine: sa.Engine | None = None) -> None:
    """Load PBP data year-by-year with column whitelist and memory guards.

    Args:
        seasons: List of NFL season years to ingest. Each year loaded independently.
        engine: SQLAlchemy sync engine. If None, creates from settings.

    Raises:
        MemoryError: If system memory > 80% before loading a season.
    """
    if engine is None:
        engine = get_sync_engine()

    for season in seasons:
        mem_before: float = psutil.virtual_memory().percent
        log.info("pbp_load_start", season=season, memory_pct=mem_before)

        if mem_before > 80.0:
            raise MemoryError(
                f"Memory at {mem_before:.1f}% before loading season {season} — aborting"
            )

        # Import inside function to allow test monkeypatching at module level
        import nflreadpy as nfl  # NOT nfl_data_py — that package is archived (Sep 2025)
        import polars as pl

        # Load single season — nflreadpy returns a Polars DataFrame
        df: pl.DataFrame = nfl.load_pbp([season])

        # Select only whitelisted columns that exist in this season's data.
        # Available-only filter prevents KeyError if a season lacks a column.
        available: list[str] = [c for c in PBP_COLUMNS if c in df.columns]
        df = df.select(available)

        # Convert to pandas for SQLAlchemy to_sql — Polars not accepted by to_sql directly.
        df_pd = df.to_pandas()

        # Chunked write: append + UniqueConstraint on (game_id, play_id) handles duplicates.
        # NEVER use if_exists='replace' — drops and recreates the table (RESEARCH.md Pitfall 5).
        df_pd.to_sql(
            "play_by_play",
            engine,
            if_exists="append",
            index=False,
            chunksize=1000,
            method="multi",
        )

        mem_after: float = psutil.virtual_memory().percent
        log.info(
            "pbp_load_done",
            season=season,
            rows=len(df_pd),
            memory_pct=mem_after,
        )

        # Explicit free before next season — prevents OOM accumulation across loop.
        del df, df_pd
        gc.collect()
