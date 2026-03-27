"""NFL game schedule ingestion module (QUANT-04 fix).

Populates the games table from nflreadpy.load_schedules().
The games table is the parent FK for odds_snapshots; an empty games table
causes load_snapshots() LEFT JOIN to produce NULL game_start_time for all
rows, making BacktestEngine return sample_size=0.

nflreadpy.load_schedules() returns a Polars DataFrame.
Column rename: "gameday" -> "game_date" to match Game ORM model.
"""
from __future__ import annotations

import gc

import nflreadpy as nfl  # NOT nfl_data_py — archived Sep 2025
import polars as pl
import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sportsbet.db.connection import get_sync_engine
from sportsbet.db.models import Game

log = structlog.get_logger()

GAMES_COLUMNS: list[str] = [
    "game_id",
    "season",
    "week",
    "home_team",
    "away_team",
    "gameday",    # renamed to "game_date" via _COLUMN_RENAMES
    "stadium",
]

_COLUMN_RENAMES: dict[str, str] = {
    "gameday": "game_date",
}


def ingest_games_seasons(
    seasons: list[int], engine: sa.Engine | None = None
) -> None:
    """Load NFL game schedule rows for the specified seasons into games table.

    Uses pg_insert ON CONFLICT DO NOTHING — safe to re-run; existing rows
    are not overwritten. Applies Polars-first write path: nflreadpy returns
    Polars, .to_pandas() called only before to_dict(orient='records').

    Args:
        seasons: NFL season years to ingest.
        engine: SQLAlchemy sync engine; creates one via get_sync_engine() if None.
    """
    if engine is None:
        engine = get_sync_engine()

    for season in seasons:
        log.info("ingesting_games", season=season)
        try:
            df: pl.DataFrame = nfl.load_schedules([season])
        except Exception as exc:
            log.warning("games_load_failed", season=season, error=str(exc))
            gc.collect()
            continue

        # Select only the columns we need; skip missing columns gracefully
        available = [c for c in GAMES_COLUMNS if c in df.columns]
        df = df.select(available)

        # Drop rows with NULL game_id or game_date — cannot insert without PK
        if "game_id" in df.columns:
            df = df.filter(pl.col("game_id").is_not_null())
        if "gameday" in df.columns:
            df = df.filter(pl.col("gameday").is_not_null())

        # Rename to match schema
        df = df.rename({k: v for k, v in _COLUMN_RENAMES.items() if k in df.columns})

        if df.is_empty():
            log.warning("games_empty_after_filter", season=season)
            gc.collect()
            continue

        rows = df.to_pandas().to_dict(orient="records")
        with engine.begin() as conn:
            stmt = pg_insert(Game).values(rows).on_conflict_do_nothing(index_elements=["game_id"])
            conn.execute(stmt)

        log.info("games_ingested", season=season, rows=len(rows))
        gc.collect()
