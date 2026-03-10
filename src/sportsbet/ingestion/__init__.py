"""NFL data ingestion package.

Provides year-by-year, memory-safe ingestion loops for:
- PBP (play-by-play) via nflreadpy.load_pbp()
- Player weekly stats via nflreadpy.load_player_stats()
- NGS (Next Gen Stats) via nflreadpy.load_nextgen_stats()
- Odds snapshots via write_odds_snapshot() with Pydantic v2 validation
"""
