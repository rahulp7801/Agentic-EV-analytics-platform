"""Ingest 2025-26 NBA player season stats into nba_player_stats.

Run from the repo root:
    set OPENBLAS_NUM_THREADS=1
    python ingest_stats_2025.py
"""
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import sys
sys.path.insert(0, "src")
sys.path.insert(0, "site-packages")

from dotenv import load_dotenv
load_dotenv()

import gc
print("Importing pandas...", flush=True)
import pandas as pd
print("Importing nba_api...", flush=True)
from nba_api.stats.endpoints import LeagueDashPlayerStats
print("Connecting to DB...", flush=True)
import sqlalchemy as sa
from sportsbet.db.connection import get_sync_engine

engine = get_sync_engine()

SEASON = 2025
season_str = "2025-26"

print(f"Fetching {season_str} stats from NBA.com...", flush=True)
stats = LeagueDashPlayerStats(
    season=season_str,
    season_type_all_star="Regular Season",
    per_mode_detailed="Totals",
    timeout=60,
)

df = stats.get_data_frames()[0]
print(f"Got {len(df)} rows from NBA.com", flush=True)

NBA_COLUMNS = ["PLAYER_ID","PLAYER_NAME","TEAM_ID","TEAM_ABBREVIATION","GP","MIN","PTS","REB","AST","FG3M","STL","BLK"]
RENAME_MAP = {"PLAYER_ID":"player_id","PLAYER_NAME":"player_name","TEAM_ID":"team_id","TEAM_ABBREVIATION":"team_abbreviation","GP":"games_played","MIN":"minutes","PTS":"points","REB":"rebounds","AST":"assists","FG3M":"threes_made","STL":"steals","BLK":"blocks"}

df = df[[c for c in NBA_COLUMNS if c in df.columns]].rename(columns=RENAME_MAP)
df["season"] = SEASON

# Delete existing 2025 rows first to avoid UniqueViolation on re-run
with engine.connect() as conn:
    result = conn.execute(sa.text("DELETE FROM nba_player_stats WHERE season = :s"), {"s": SEASON})
    conn.commit()
    print(f"Deleted {result.rowcount} existing season={SEASON} rows", flush=True)

df.to_sql("nba_player_stats", engine, if_exists="append", index=False, chunksize=500, method="multi")
print(f"Inserted {len(df)} rows for season {SEASON}", flush=True)

del df
gc.collect()
print("Done.", flush=True)
