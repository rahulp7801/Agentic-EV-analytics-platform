"""Execute the scan graph and repeatable ingestion against disposable PostgreSQL."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
import pandas as pd
import pytest
import sqlalchemy as sa
import polars as pl
from unittest.mock import patch

from sportsbet.ingestion.upsert import upsert_rows
from sportsbet.ledger import Ledger
from sportsbet.scan import evaluate_event

pytestmark = pytest.mark.skipif(
    not os.environ.get('SPORTSBET_TEST_DATABASE_URL'), reason='Disposable test database required'
)


def test_nfl_refresh_applies_schedule_corrections_and_clears_ambiguous_context():
    from sportsbet.ingestion.games import ingest_games_seasons
    from sportsbet.ingestion.player_stats import ingest_player_stats_seasons
    engine = sa.create_engine(os.environ['SPORTSBET_TEST_DATABASE_URL'])
    identity = uuid.uuid4().hex[:20]
    game = dict(game_id=identity,season=2026,week=1,home_team='ZZ1',away_team='ZZ2',gameday='2026-09-10')
    stat = dict(player_id=identity,player_display_name='Fixture',season=2026,week=1,team='ZZ1',passing_yards=200,season_type='REG')
    try:
        for corrected in (False, True):
            if corrected:
                game.update(home_team='ZZ2',away_team='ZZ1',gameday='2026-09-12')
                stat['passing_yards'] = 225
            with patch('sportsbet.ingestion.games.nfl.load_schedules',return_value=pl.DataFrame([game])), \
                 patch('sportsbet.ingestion.player_stats.nfl.load_player_stats',return_value=pl.DataFrame([stat])):
                ingest_games_seasons([2026],engine)
                ingest_player_stats_seasons([2026],engine)
            with engine.connect() as conn:
                row = conn.execute(sa.text('SELECT passing_yards,opponent_team,home_away FROM player_stats WHERE player_id=:id'),{'id':identity}).one()
                assert tuple(row) == (225 if corrected else 200,'ZZ2','away' if corrected else 'home')
                stored_date=conn.execute(sa.text('SELECT game_date FROM games WHERE game_id=:id'),{'id':identity}).scalar_one()
                assert stored_date.isoformat() == game['gameday']
        # Multiple schedule matches must not silently choose an opponent or retain obsolete context.
        duplicate = {**game,'game_id':identity+'x','away_team':'ZZ3','home_team':'ZZ1'}
        with patch('sportsbet.ingestion.games.nfl.load_schedules',return_value=pl.DataFrame([duplicate])), \
             patch('sportsbet.ingestion.player_stats.nfl.load_player_stats',return_value=pl.DataFrame([stat])):
            ingest_games_seasons([2026],engine)
            ingest_player_stats_seasons([2026],engine)
        with engine.connect() as conn:
            row=conn.execute(sa.text('SELECT opponent_team,home_away FROM player_stats WHERE player_id=:id'),{'id':identity}).one()
            assert tuple(row) == (None,None)
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text('DELETE FROM player_stats WHERE player_id=:id'),{'id':identity})
            conn.execute(sa.text('DELETE FROM games WHERE game_id IN (:id,:duplicate)'),{'id':identity,'duplicate':identity+'x'})
        engine.dispose()


def test_repeatable_stat_refresh_applies_corrections():
    engine = sa.create_engine(os.environ['SPORTSBET_TEST_DATABASE_URL'])
    player = uuid.uuid4().hex[:20]
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                row = dict(player_id=player, season=2025, week=1, passing_yards=200)
                for yards in (200, 225):
                    row['passing_yards'] = yards
                    pd.DataFrame([row]).to_sql('player_stats', conn, if_exists='append', index=False,
                        method=upsert_rows(['player_id', 'season', 'week']))
                values = conn.execute(sa.text('SELECT passing_yards FROM player_stats WHERE player_id=:id'), {'id':player}).scalars().all()
                assert values == [225]
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize('sport', ['nba', 'nfl'])
async def test_scan_graph_runs_real_sql_and_excludes_target_game(sport, tmp_path):
    url = os.environ['SPORTSBET_TEST_DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://')
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    identity = uuid.uuid4().hex[:16]
    player_id = int(uuid.uuid4().int % 1000000000) if sport == 'nba' else identity
    player = 'Test ' + identity
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=2)
    target = start.astimezone(ZoneInfo('America/New_York')).date()
    season = target.year if target.month >= (10 if sport == 'nba' else 9) else target.year-1
    market = 'player_points' if sport == 'nba' else 'player_pass_yds'
    count = 40 if sport == 'nba' else 34
    event = dict(id=identity, home_team='Home', away_team='Away', commence_time=start.isoformat(),
        bookmakers=[dict(key='book', last_update=now.isoformat(), markets=[dict(key=market, outcomes=[
            dict(name='Over', description=player, point=20.5, price=100)])])])
    ledger = Ledger(tmp_path / 'audit.sqlite')
    table = 'nba_player_gamelogs' if sport == 'nba' else 'player_stats'
    try:
        async with pool.acquire() as conn:
            for i in range(count+1):
                game_date = target-timedelta(days=count-i)
                stat = 30 if i < 24 or i == count else 10
                if sport == 'nba':
                    await conn.execute('INSERT INTO nba_player_gamelogs(player_id,player_name,game_id,game_date,season,points) VALUES($1,$2,$3,$4,$5,$6)',
                        player_id,player,f'{identity}{i:02}',game_date,season-1,stat)
                else:
                    row_season, week = season-2+i//17, i%17+1
                    await conn.execute('INSERT INTO games(game_id,season,week,home_team,away_team,game_date) VALUES($1,$2,$3,$4,$5,$6)',
                        f'{identity}{i:02}',row_season,week,'TST','OPP',game_date)
                    await conn.execute('INSERT INTO player_stats(player_id,player_name,season,week,team,passing_yards) VALUES($1,$2,$3,$4,$5,$6)',
                        player_id,player,row_season,week,'TST',stat)
        result = await evaluate_event(pool,event,sport,ledger,identity)
        predictions = ledger.predictions()
        assert len(predictions) == 1
        assert predictions[0]['model_probability'] == pytest.approx(24/count, abs=1e-6)
        # NBA's 60% vs 50% quote passes policy; NFL's larger edge remains audited even if capped.
        if sport == 'nba':
            assert result['signals'][0]['sample_size'] == count
            assert result['signals'][0]['direction'] == 'over'
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f'DELETE FROM {table} WHERE player_id=$1',player_id)
            if sport == 'nfl':
                await conn.execute('DELETE FROM games WHERE game_id LIKE $1',identity+'%')
        await pool.close()
