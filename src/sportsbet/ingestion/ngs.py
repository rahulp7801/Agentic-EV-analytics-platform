"""Next Gen Stats (NGS) ingestion module.

Loads AWS Next Gen Stats for three stat types (passing, receiving, rushing)
per season. NGS data is only available from 2016 onward — any earlier season
raises ValueError immediately (RESEARCH.md Pitfall 6).

nflreadpy.load_nextgen_stats() returns a Polars DataFrame.
"""
from __future__ import annotations

import gc

import polars as pl
import nflreadpy as nfl  # NOT nfl_data_py — archived Sep 2025
import sqlalchemy as sa
import structlog

from sportsbet.db.connection import get_sync_engine

log = structlog.get_logger()

# NGS data availability guard — data not available before 2016 (RESEARCH.md Pitfall 6).
NGS_MIN_SEASON: int = 2016

NGS_PASSING_COLUMNS: list[str] = [
    "season",
    "week",
    "player_gsis_id",
    "team_abbr",
    "player_position",
    "avg_time_to_throw",
    "avg_completed_air_yards",
    "avg_intended_air_yards",
    "aggressiveness",
    "passer_rating",
    "attempts",
]

NGS_RECEIVING_COLUMNS: list[str] = [
    "season",
    "week",
    "player_gsis_id",
    "team_abbr",
    "player_position",
    "avg_separation",
    "avg_cushion",
    "avg_yac",
    "avg_yac_above_expectation",
    "catch_percentage",
    "targets",
    "receptions",
]

NGS_RUSHING_COLUMNS: list[str] = [
    "season",
    "week",
    "player_gsis_id",
    "team_abbr",
    "player_position",
    "efficiency",
    "percent_attempts_gte_eight_defenders",
    "rush_yards_over_expected",
    "avg_time_to_los",
    "rush_attempts",
]

# All three stat type configs in a single ordered list — iterated in one loop call.
_NGS_STAT_CONFIGS: list[tuple[str, list[str]]] = [
    ("passing", NGS_PASSING_COLUMNS),
    ("receiving", NGS_RECEIVING_COLUMNS),
    ("rushing", NGS_RUSHING_COLUMNS),
]


def ingest_ngs_seasons(seasons: list[int], engine: sa.Engine | None = None) -> None:
    """Load NGS tracking data for three stat types across the specified seasons.

    Loops all 3 stat_types (passing/receiving/rushing) in a single call per season.
    Each stat_type gets a column whitelist applied before write.

    Args:
        seasons: NFL season years. Each must be >= NGS_MIN_SEASON (2016).
        engine: SQLAlchemy sync engine. If None, creates from settings.

    Raises:
        ValueError: If any season < NGS_MIN_SEASON (2016).
    """
    if engine is None:
        engine = get_sync_engine()

    for season in seasons:
        if season < NGS_MIN_SEASON:
            raise ValueError(
                f"NGS data not available before {NGS_MIN_SEASON}. "
                f"Requested season: {season}"
            )

        for stat_type, columns in _NGS_STAT_CONFIGS:
            log.info("ngs_load_start", season=season, stat_type=stat_type)

            df: pl.DataFrame = nfl.load_nextgen_stats([season], stat_type=stat_type)

            # Available-only column filter — prevents KeyError on sparse seasons.
            available: list[str] = [c for c in columns if c in df.columns]
            df = df.select(available)

            # Add stat_type column so rows are distinguishable in the unified ngs_stats table.
            df = df.with_columns(pl.lit(stat_type).alias("stat_type"))

            df.to_pandas().to_sql(
                "ngs_stats",
                engine,
                if_exists="append",
                index=False,
                chunksize=1000,
                method="multi",
            )

            del df
            gc.collect()

            log.info("ngs_load_done", season=season, stat_type=stat_type)
