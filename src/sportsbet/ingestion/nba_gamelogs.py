"""NBA per-game log ingestion via nba_api PlayerGameLogs bulk endpoint.

Uses PlayerGameLogs (one HTTP call per season) to load individual game rows into
nba_player_gamelogs. nba_api returns pandas DataFrames — no .to_pandas() call needed.

MATCHUP parsing:
  - "LAL vs. GSW" -> is_home=True,  opponent_team="GSW"
  - "LAL @ BOS"   -> is_home=False, opponent_team="BOS"

MATCHUP column is dropped after derivation — only is_home and opponent_team are stored.

Rate limiting: mandatory time.sleep(1) between seasons per NBA.com rate limit policy
(mirrors nba.py pattern from Phase 10).

Memory management: gc.collect() called after each season's to_sql() to prevent
OOM accumulation across multi-season backfills (mirrors nba.py Phase 10 pattern).

Import pattern: PlayerGameLogs imported at module level (not inside closure) so that
unittest.mock.patch("sportsbet.ingestion.nba_gamelogs.PlayerGameLogs") can intercept
calls from tests — Phase 8 locked decision on module-level import patchability.

get_sync_engine imported lazily inside main() only to avoid import-time DB connection
during tests or module-level imports.
"""
from __future__ import annotations

import argparse
import gc
import sys
import time
from typing import Optional

import pandas as pd
import sqlalchemy as sa
import structlog
from nba_api.stats.endpoints import PlayerGameLogs

log = structlog.get_logger(__name__)

# Column whitelist — only columns needed by downstream Phase 18 gamelog queries.
# MATCHUP is included for is_home/opponent_team derivation but dropped before to_sql.
GAMELOG_COLUMNS: list[str] = [
    "PLAYER_ID",
    "PLAYER_NAME",
    "TEAM_ABBREVIATION",
    "GAME_ID",
    "GAME_DATE",
    "MATCHUP",
    "MIN",
    "PTS",
    "REB",
    "AST",
    "FG3M",
    "STL",
    "BLK",
]

# Rename map: nba_api column names -> ORM/DB column names (nba_player_gamelogs table).
GAMELOG_RENAME_MAP: dict[str, str] = {
    "PLAYER_ID": "player_id",
    "PLAYER_NAME": "player_name",
    "TEAM_ABBREVIATION": "team_abbreviation",
    "GAME_ID": "game_id",
    "GAME_DATE": "game_date",
    "MIN": "minutes",
    "PTS": "points",
    "REB": "rebounds",
    "AST": "assists",
    "FG3M": "threes_made",
    "STL": "steals",
    "BLK": "blocks",
}


def ingest_nba_gamelogs_season(
    season: int,
    engine: Optional[sa.Engine] = None,
) -> None:
    """Load NBA per-game logs for a single season into nba_player_gamelogs.

    Args:
        season: NBA season start year (e.g. 2023 for 2023-24 season).
        engine: SQLAlchemy sync engine. If None, creates from settings.

    Notes:
        - One HTTP call per season via PlayerGameLogs (Regular Season).
        - time.sleep(1) after API call — mandatory NBA.com rate limit policy.
        - is_home derived from MATCHUP: "@" present => away game.
        - opponent_team derived from MATCHUP split on " @ " or " vs. ".
        - MATCHUP column dropped after derivation.
        - gc.collect() called after to_sql to prevent OOM accumulation.
    """
    if engine is None:
        from sportsbet.db.connection import get_sync_engine
        engine = get_sync_engine()

    season_str = f"{season}-{str(season + 1)[-2:]}"
    log.info("nba_gamelogs_ingestion.season_start", season=season_str)

    # One bulk HTTP call for all players in this season.
    logs = PlayerGameLogs(
        season_nullable=season_str,
        season_type_nullable="Regular Season",
        timeout=30,
    )

    # Mandatory rate limit delay — NBA.com enforces per-request throttling.
    time.sleep(1)

    # nba_api returns pandas DataFrame directly — no .to_pandas() needed.
    df: pd.DataFrame = logs.get_data_frames()[0]

    # Apply column whitelist — keep only the columns we need.
    df = df[GAMELOG_COLUMNS].copy()

    # Derive is_home: MATCHUP contains "@" for away games; "vs." for home games.
    df["is_home"] = ~df["MATCHUP"].str.contains("@")

    # Derive opponent_team: split on " @ " or " vs. " and take the last element.
    # .str.strip() guard handles edge-case whitespace (e.g. "LAL  @  BOS").
    df["opponent_team"] = (
        df["MATCHUP"]
        .str.split(r" @ | vs\. ", regex=True)
        .str[-1]
        .str.strip()
    )

    # Drop raw MATCHUP — not stored in DB.
    df = df.drop(columns=["MATCHUP"])

    # Rename to ORM column names.
    df = df.rename(columns=GAMELOG_RENAME_MAP)

    # Add season year as integer column for partitioning and queries.
    df["season"] = season

    # Convert game_date string to Python date objects.
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date

    # Append rows — UniqueConstraint on (player_id, game_id) handles re-runs.
    # NEVER use if_exists='replace' — drops and recreates the table.
    df.to_sql("nba_player_gamelogs", engine, if_exists="append", index=False)

    log.info(
        "nba_gamelogs_ingestion.season_complete",
        season=season_str,
        rows=len(df),
    )

    # Explicit free before potential next call — prevents OOM accumulation.
    del df
    gc.collect()


def main() -> None:
    """CLI entry point for NBA gamelog backfill.

    Usage:
        python -m sportsbet.ingestion.nba_gamelogs --start-season 2020 --end-season 2023
    """
    parser = argparse.ArgumentParser(
        description="Ingest NBA per-game logs into nba_player_gamelogs table."
    )
    parser.add_argument(
        "--start-season",
        type=int,
        default=2022,
        help="First season start year to ingest (e.g. 2022 for 2022-23). Default: 2022.",
    )
    parser.add_argument(
        "--end-season",
        type=int,
        default=2024,
        help="Last season start year to ingest (inclusive). Default: 2024.",
    )
    args = parser.parse_args()

    # Lazy engine import — avoids import-time DB connection during tests.
    from sportsbet.db.connection import get_sync_engine
    engine = get_sync_engine()

    for season in range(args.start_season, args.end_season + 1):
        ingest_nba_gamelogs_season(season, engine)


if __name__ == "__main__":
    main()
    sys.exit(0)
