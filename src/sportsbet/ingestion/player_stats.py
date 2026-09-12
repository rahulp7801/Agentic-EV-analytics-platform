"""Player weekly stats ingestion module.

Loads weekly player statistics via nflreadpy.load_player_stats().
Applies a column whitelist (PLAYER_STATS_COLUMNS) and renames nflreadpy fields
to match the player_stats table schema where field names differ.

nflreadpy.load_player_stats() returns a Polars DataFrame.
"""
from __future__ import annotations

import gc
from datetime import datetime, timezone
from sportsbet.ingestion.upsert import upsert_rows
from sportsbet.ingestion.provenance import stat_batch_sha256, stat_row_sha256

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
    "player_display_name",
    "team",
    "opponent_team",
    "season",
    "week",
    "recent_team",   # renamed to 'team' to match schema
    "position",
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "passing_interceptions",
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
    "player_display_name": "player_name",
    "passing_interceptions": "interceptions",
}


def ingest_player_stats_seasons(
    seasons: list[int], engine: sa.Engine | None = None
) -> None:
    """Load player weekly stats for the specified seasons.

    Applies column whitelist and renames nflreadpy fields to match the
    player_stats schema. Upserts stats and enriches unambiguous schedule context
    in one transaction, so a failed refresh cannot publish partially updated rows.

    Args:
        seasons: List of NFL season years to ingest.
        engine: SQLAlchemy sync engine. If None, creates from settings.
    """
    if engine is None:
        engine = get_sync_engine()

    for season in seasons:
        log.info("player_stats_load_start", season=season)

        df: pl.DataFrame = nfl.load_player_stats([season])

        if "season_type" in df.columns:
            df = df.filter(pl.col("season_type") == "REG")
        # nflverse also includes unattributed team plays with no player ID.
        # They cannot be assigned to a player and must not abort the season load.
        before = df.height
        df = df.filter(pl.col("player_id").is_not_null() & (pl.col("player_id").str.strip_chars() != ""))
        if df.height != before:
            log.warning("player_stats_unattributed_rows_skipped", season=season, rows=before-df.height)
        if df.is_empty():
            log.warning("player_stats_no_identified_players", season=season)
            continue
        if "team" in df.columns and "recent_team" in df.columns:
            df = df.drop("recent_team")
        if "passing_interceptions" in df.columns and "interceptions" in df.columns:
            df = df.drop("interceptions")

        # Available-only filter — prevents KeyError if a season lacks a column.
        available: list[str] = [c for c in PLAYER_STATS_COLUMNS if c in df.columns]
        df = df.select(available)

        # Rename nflreadpy fields to match our schema (only if present in df).
        rename_map = {k: v for k, v in _COLUMN_RENAMES.items() if k in df.columns}
        if rename_map:
            df = df.rename(rename_map)

        frame=df.to_pandas()
        records=frame.to_dict('records')
        # nflverse columns can vary by season. Preserve an unavailable tracked
        # statistic as NULL so the stored evidence remains complete and the
        # settlement layer can keep that market pending instead of inventing 0.
        nullable_evidence_fields=('passing_yards','rushing_yards','receiving_yards')
        for row in records:
            for field in nullable_evidence_fields:
                row.setdefault(field,None)
        frame=frame.reindex(columns=[*frame.columns,
            *(field for field in nullable_evidence_fields if field not in frame.columns)])
        record_hashes=[stat_row_sha256('nfl',row) for row in records]
        batch_hash=stat_batch_sha256('nflverse','nfl',season,record_hashes)
        frame['source_provider']='nflverse'
        frame['source_sha256']=batch_hash
        frame['source_record_sha256']=record_hashes
        frame['source_observed_at']=datetime.now(timezone.utc)
        with engine.begin() as conn:
            frame.to_sql(
                "player_stats", conn, if_exists="append", index=False, chunksize=1000,
                method=upsert_rows(['player_id', 'season', 'week']),
            )
            conn.execute(sa.text('''
                WITH team_games AS (
                    SELECT season,week,home_team AS team,away_team AS opponent,'home' AS venue
                    FROM games WHERE season=:season
                    UNION ALL
                    SELECT season,week,away_team,home_team,'away'
                    FROM games WHERE season=:season
                ), unambiguous AS (
                    SELECT season,week,team,MIN(opponent) AS opponent,MIN(venue) AS venue
                    FROM team_games GROUP BY season,week,team HAVING COUNT(*)=1
                )
                UPDATE player_stats p SET (opponent_team,home_away)=(
                    SELECT g.opponent,g.venue FROM unambiguous g
                    WHERE p.season=g.season AND p.week=g.week AND p.team=g.team
                ) WHERE p.season=:season
            '''), {'season':season})

        del df
        gc.collect()

        log.info("player_stats_load_done", season=season)
