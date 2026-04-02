import sys, os
sys.path.insert(0, 'src')
sys.path.insert(0, 'site-packages')

from dotenv import load_dotenv
load_dotenv()

import asyncio
from sportsbet.db.connection import create_async_pool

async def check_db():
    pool = await create_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            'SELECT season, COUNT(*) g FROM nba_player_gamelogs GROUP BY season ORDER BY season'
        )
        seasons = {r['season']: r['g'] for r in rows}
        sys.stdout.write(f"DB seasons: {seasons}\n")
        sys.stdout.flush()

        if 2025 not in seasons:
            sys.stdout.write("2025 not in DB — ingesting now...\n")
            sys.stdout.flush()
        else:
            sys.stdout.write(f"2025 already in DB: {seasons[2025]} rows\n")
            sys.stdout.flush()

        dr = await conn.fetch("""
            SELECT season, COUNT(*) g, ROUND(AVG(points::float)::numeric, 2) avg
            FROM nba_player_gamelogs
            WHERE player_name ILIKE '%derozan%'
            GROUP BY season ORDER BY season
        """)
        for r in dr:
            sys.stdout.write(f"DeRozan s{r['season']}: {r['g']} games, {r['avg']} ppg\n")
            sys.stdout.flush()
    await pool.close()

asyncio.run(check_db())

# Now ingest 2025 if needed
from sportsbet.ingestion.nba_gamelogs import ingest_nba_gamelogs_season
sys.stdout.write("Ingesting season 2025...\n")
sys.stdout.flush()
ingest_nba_gamelogs_season(2025)
sys.stdout.write("Ingestion complete.\n")
sys.stdout.flush()

# Verify
async def verify():
    pool = await create_async_pool()
    async with pool.acquire() as conn:
        dr = await conn.fetch("""
            SELECT season, COUNT(*) g, ROUND(AVG(points::float)::numeric, 2) avg
            FROM nba_player_gamelogs
            WHERE player_name ILIKE '%derozan%'
            GROUP BY season ORDER BY season
        """)
        for r in dr:
            sys.stdout.write(f"[AFTER] DeRozan s{r['season']}: {r['g']} games, {r['avg']} ppg\n")
            sys.stdout.flush()
    await pool.close()

asyncio.run(verify())
