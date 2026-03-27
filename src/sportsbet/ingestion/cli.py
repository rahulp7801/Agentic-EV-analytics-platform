"""CLI entry point for NFL data ingestion.

Usage:
    python -m sportsbet.ingestion.cli --seasons 2019 2020 2021 2022 2023

Runs PBP, player stats, and NGS ingestion in sequence for the given seasons.
NGS ingestion skips any season < NGS_MIN_SEASON (2016).

Use --pbp-only to load only play-by-play data (skips player stats and NGS).
"""
from __future__ import annotations

import argparse

import structlog

from sportsbet.db.connection import get_sync_engine
from sportsbet.ingestion.games import ingest_games_seasons
from sportsbet.ingestion.ngs import NGS_MIN_SEASON, ingest_ngs_seasons
from sportsbet.ingestion.pbp import ingest_pbp_seasons
from sportsbet.ingestion.player_stats import ingest_player_stats_seasons

log = structlog.get_logger()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NFL data ingestion CLI — loads PBP, player stats, and NGS data"
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        required=True,
        help="List of NFL season years to ingest (e.g. 2019 2020 2021 2022 2023)",
    )
    parser.add_argument(
        "--pbp-only",
        action="store_true",
        help="Load play-by-play data only (skip player stats and NGS)",
    )
    parser.add_argument(
        "--games",
        action="store_true",
        help="Ingest NFL game schedules into the games table (prerequisite for backtest)",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    seasons: list[int] = args.seasons
    log.info("ingestion_start", seasons=seasons)

    log.info("ingesting_pbp", seasons=seasons)
    ingest_pbp_seasons(seasons, engine)

    if not args.pbp_only:
        log.info("ingesting_player_stats", seasons=seasons)
        ingest_player_stats_seasons(seasons, engine)

        ngs_seasons = [s for s in seasons if s >= NGS_MIN_SEASON]
        if ngs_seasons:
            log.info("ingesting_ngs", seasons=ngs_seasons)
            ingest_ngs_seasons(ngs_seasons, engine)
        else:
            log.info("ngs_skipped_all_pre_2016", seasons=seasons)

    if args.games:
        log.info("ingesting_games_schedules", seasons=seasons)
        ingest_games_seasons(seasons, engine)

    log.info("ingestion_complete", seasons=seasons)


if __name__ == "__main__":
    main()
