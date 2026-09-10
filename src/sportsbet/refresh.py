"""Refresh the historical game samples used by the scheduled prop worker."""
import argparse
from datetime import date

from sportsbet.db.connection import get_sync_engine
from sportsbet.ingestion.games import ingest_games_seasons
from sportsbet.ingestion.nba_gamelogs import ingest_nba_gamelogs_season
from sportsbet.ingestion.player_stats import ingest_player_stats_seasons


def refresh(sport: str, today: date, backfill: bool = False):
    start = today.year if today.month >= (10 if sport == 'nba' else 9) else today.year-1
    # NFL requires multiple seasons to reach the minimum sample; NBA prior season covers opening night.
    years = list(range(start-(2 if sport == 'nfl' else 1), start+1)) if backfill else [start]
    engine = get_sync_engine()
    try:
        if sport == 'nfl':
            ingest_games_seasons(years, engine)
            ingest_player_stats_seasons(years, engine)
        else:
            for season in years:
                ingest_nba_gamelogs_season(season, engine)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=['nba','nfl','both'], default='both')
    parser.add_argument('--backfill', action='store_true')
    args = parser.parse_args()
    try:
        for sport in ['nfl','nba'] if args.sport == 'both' else [args.sport]:
            refresh(sport, date.today(), args.backfill)
    except Exception as exc:
        # Provider/DB exception text can contain URLs with credentials.
        raise SystemExit(f'Stat refresh failed ({type(exc).__name__})') from None


if __name__ == '__main__':
    main()
