"""Legacy entry point. Use the maintained read-only worker or projection collector."""
if __name__ == "__main__":
    raise SystemExit(
        "The old PrizePicks EV demo used invented single-pick prices and has been retired. "
        "For actual sportsbook quotes: python -m sportsbet.scan --sport nba. "
        "For raw PrizePicks projections: python -m sportsbet.ingestion.prizepicks --sport nba."
    )
