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
from sportsbet.ingestion.provenance import stat_row_sha256
from sportsbet.ledger import Ledger
from sportsbet.scan import evaluate_event, quotes_from_event
from sportsbet.settlement import settle_final_props

pytestmark = pytest.mark.skipif(
    not os.environ.get('SPORTSBET_TEST_DATABASE_URL'), reason='Disposable test database required'
)


def test_final_prop_settlement_uses_real_postgres_and_retains_provenance():
    url=os.environ['SPORTSBET_TEST_DATABASE_URL'];ledger=Ledger(database_url=url)
    identity=uuid.uuid4().hex[:16];player_id=int(uuid.uuid4().int%900000000)+1
    now=datetime.now(timezone.utc);day=(now-timedelta(days=1)).date()
    payload=dict(game_id=identity,player='Settlement Fixture',player_id=str(player_id),sport='nba',
        game_date=day.isoformat(),home_team='Home',away_team='Away',prop_type='points',direction='over',
        line=20.5,sportsbook='book',american_odds=100,model_probability=.6,
        captured_at=(now-timedelta(days=1,hours=3)).isoformat(),
        game_start_time=(now-timedelta(days=1,hours=2)).isoformat(),model_version=identity)
    engine=sa.create_engine(url)
    try:
        stat=dict(player_id=player_id,game_id=identity,game_date=day,team_abbreviation='H',
            points=21,rebounds=0,assists=0)
        with engine.begin() as conn:
            conn.execute(sa.text("""INSERT INTO nba_player_gamelogs
                (player_id,player_name,game_id,game_date,season,team_abbreviation,points,rebounds,assists,
                 source_provider,source_sha256,source_record_sha256,source_observed_at)
                VALUES (:player,:name,:game,:day,2025,'H',21,0,0,'nba',:source,:record,:observed)"""),
                {'player':player_id,'name':payload['player'],'game':identity,'day':day,
                 'source':'a'*64,'record':stat_row_sha256('nba',stat),'observed':now})
        key=ledger.record(identity,payload)
        schedule=dict(status='complete',captured_at=now.isoformat(),games=[dict(
            provider_event_id='espn-'+identity,date=day.isoformat(),home_name='Home',away_name='Away',
            completed=True,game_time=payload['game_start_time'])])
        assert settle_final_props(ledger,'nba',schedule)['settled']==1
        row=next(item for item in ledger.predictions() if item['prediction_id']==key)
        assert row['outcome'] is True and row['actual_value']==21
        assert row['outcome_source']=='observed_final_stats' and identity in row['outcome_ref']
        assert row['outcome_evidence']['stat_record_sha256']==stat_row_sha256('nba',stat)
        report=ledger.report(model_version=identity)
        assert report['settled_count']==1 and report['unverified_settlements']==0
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text('DELETE FROM nba_player_gamelogs WHERE game_id=:id'),{'id':identity})
            conn.execute(sa.text('DELETE FROM analytics.predictions WHERE scan_id=:id'),{'id':identity})
            conn.execute(sa.text('DELETE FROM analytics.quotes WHERE identity=:id'),{'id':ledger.quote_identity(payload)})
        engine.dispose()


def test_nba_fallback_protects_official_rows_and_applies_corrections_atomically():
    from sportsbet.ingestion.nba_espn import store_rows
    engine=sa.create_engine(os.environ['SPORTSBET_TEST_DATABASE_URL'])
    game=uuid.uuid4().hex[:18]
    now=datetime.now(timezone.utc)
    rows=[dict(player_id=i,game_id=game,player_name='Fallback fixture',game_date=now.date(),
        team_abbreviation='BOS',season=2025,points=10,rebounds=0,assists=0,
        source_provider='espn',source_sha256='a'*64,source_observed_at=now) for i in (1,2)]
    for row in rows:row['source_record_sha256']=stat_row_sha256('nba',row)
    try:
        with engine.begin() as conn:
            official=rows[0]|dict(points=20,source_provider='nba',source_sha256='c'*64)
            official['source_record_sha256']=stat_row_sha256('nba',official)
            conn.execute(sa.text("""INSERT INTO nba_player_gamelogs(player_id,player_name,game_id,game_date,
                team_abbreviation,season,points,rebounds,assists,source_provider,source_sha256,
                source_record_sha256,source_observed_at) VALUES (:player_id,:player_name,:game_id,:game_date,
                :team_abbreviation,:season,:points,:rebounds,:assists,:source_provider,:source_sha256,
                :source_record_sha256,:source_observed_at)"""),official)
        store_rows(engine,rows)
        corrected=[r|{'points':11} for r in rows]
        for row in corrected:row['source_record_sha256']=stat_row_sha256('nba',row)
        store_rows(engine,corrected)
        with engine.connect() as conn:
            actual=conn.execute(sa.text('SELECT player_id,points,source_provider FROM nba_player_gamelogs WHERE game_id=:game ORDER BY player_id'),{'game':game}).all()
            assert [tuple(r) for r in actual]==[(1,20,'nba'),(2,11,'espn')]
        # Removing a participant cannot leave stale data while claiming refresh success.
        with pytest.raises(ValueError,match='reconciliation required'): store_rows(engine,rows[:1])
        # A later official correction takes priority, including resetting provenance.
        with engine.begin() as conn:
            official=rows[1]|dict(points=15,source_provider='nba',source_sha256='c'*64)
            official['source_record_sha256']=stat_row_sha256('nba',official)
            pd.DataFrame([official]).to_sql(
                'nba_player_gamelogs',conn,if_exists='append',index=False,method=upsert_rows(['player_id','game_id']))
        store_rows(engine,rows)
        with engine.connect() as conn:
            actual=conn.execute(sa.text('SELECT points,source_provider,source_sha256 FROM nba_player_gamelogs WHERE game_id=:game AND player_id=2'),{'game':game}).one()
            assert tuple(actual)==(15,'nba','c'*64)
        # Constraint failure rolls back the other rows in the same batch.
        with pytest.raises(sa.exc.IntegrityError): store_rows(engine,[rows[0]|dict(player_id=3),rows[1]|dict(player_id=4,source_provider='unknown')])
        with engine.connect() as conn:
            assert conn.execute(sa.text('SELECT count(*) FROM nba_player_gamelogs WHERE game_id=:game'),{'game':game}).scalar_one()==2
    finally:
        with engine.begin() as conn: conn.execute(sa.text('DELETE FROM nba_player_gamelogs WHERE game_id=:game'),{'game':game})
        engine.dispose()


def test_dashboard_game_logs_expose_stats_and_reject_ambiguous_nfl_games():
    engine=sa.create_engine(os.environ['SPORTSBET_TEST_DATABASE_URL'])
    name='View '+uuid.uuid4().hex[:12]
    identity=uuid.uuid4().hex[:18]
    try:
        observed=datetime.now(timezone.utc);source='d'*64
        with engine.begin() as conn:
            conn.execute(sa.text("""INSERT INTO nba_player_gamelogs(player_id,player_name,game_id,game_date,
                season,points,source_provider,source_sha256,source_record_sha256,source_observed_at)
                VALUES (1,:name,:id,'2026-01-01',2025,0,'nba',:source,:source,:observed)"""),
                {'name':name,'id':identity,'source':source,'observed':observed})
            conn.execute(sa.text("""INSERT INTO player_stats(player_id,player_name,team,season,week,
                passing_yards,source_provider,source_sha256,source_record_sha256,source_observed_at)
                VALUES (:id,:name,'VV1',2026,1,210,'nflverse',:source,:source,:observed)"""),
                {'name':name,'id':identity,'source':source,'observed':observed})
            conn.execute(sa.text("INSERT INTO games(game_id,season,week,home_team,away_team,game_date) VALUES (:id,2026,1,'VV1','VV2','2026-09-10')"),{'id':identity})
            rows=conn.execute(sa.text('SELECT sport,payload FROM dashboard_gamelogs WHERE player_name=:name'),{'name':name}).all()
            result=dict(rows)
            assert result['nba']['points']==0 and result['nba']['rebounds'] is None
            assert result['nfl']['pass_yds']==210 and result['nfl']['is_home'] is True
            assert result['nfl']['opponent']=='VV2'
            assert 'player_id' not in result['nfl']
            conn.execute(sa.text("INSERT INTO games(game_id,season,week,home_team,away_team,game_date) VALUES (:id,2026,1,'VV1','VV3','2026-09-11')"),{'id':identity+'x'})
            assert conn.execute(sa.text("SELECT count(*) FROM dashboard_gamelogs WHERE sport='nfl' AND player_name=:name"),{'name':name}).scalar_one()==0
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text('DELETE FROM nba_player_gamelogs WHERE game_id=:id'),{'id':identity})
            conn.execute(sa.text('DELETE FROM player_stats WHERE player_id=:id'),{'id':identity})
            conn.execute(sa.text('DELETE FROM games WHERE game_id IN (:id,:other)'),{'id':identity,'other':identity+'x'})
        engine.dispose()


def test_nfl_refresh_applies_schedule_corrections_and_clears_ambiguous_context():
    from sportsbet.ingestion.games import ingest_games_seasons
    from sportsbet.ingestion.player_stats import ingest_player_stats_seasons
    engine = sa.create_engine(os.environ['SPORTSBET_TEST_DATABASE_URL'])
    identity = uuid.uuid4().hex[:19]
    game = dict(game_id=identity,season=2026,week=1,home_team='ZZ1',away_team='ZZ2',gameday='2026-09-10')
    stat = dict(player_id=identity,player_display_name='Fixture',season=2026,week=1,team='ZZ1',passing_yards=200,passing_interceptions=2,season_type='REG')
    try:
        for corrected in (False, True):
            if corrected:
                game.update(home_team='ZZ2',away_team='ZZ1',gameday='2026-09-12')
                stat['passing_yards'] = 225
            with patch('sportsbet.ingestion.games.nfl.load_schedules',return_value=pl.DataFrame([game])), \
                 patch('sportsbet.ingestion.player_stats.nfl.load_player_stats',return_value=pl.DataFrame([stat, stat | dict(player_id=None,player_display_name=None)])):
                ingest_games_seasons([2026],engine)
                ingest_player_stats_seasons([2026],engine)
            with engine.connect() as conn:
                row = conn.execute(sa.text('SELECT passing_yards,opponent_team,home_away FROM player_stats WHERE player_id=:id'),{'id':identity}).one()
                assert tuple(row) == (225 if corrected else 200,'ZZ2','away' if corrected else 'home')
                assert conn.execute(sa.text('SELECT interceptions FROM player_stats WHERE player_id=:id'),{'id':identity}).scalar_one() == 2
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
                row = dict(player_id=player, season=2025, week=1, passing_yards=200,
                    source_provider='nflverse',source_sha256='e'*64,
                    source_record_sha256='f'*64,source_observed_at=datetime.now(timezone.utc))
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
    home,away=('Boston Celtics','Los Angeles Lakers') if sport=='nba' else ('Home','Away')
    event = dict(id=identity, home_team=home, away_team=away, commence_time=start.isoformat(),
        bookmakers=[dict(key='book', last_update=now.isoformat(), markets=[dict(key=market, outcomes=[
            dict(name='Over', description=player, point=20.5, price=100)])])])
    ledger = Ledger(tmp_path / 'audit.sqlite')
    table = 'nba_player_gamelogs' if sport == 'nba' else 'player_stats'
    try:
        async with pool.acquire() as conn:
            for i in range(count+1):
                game_date = target-timedelta(days=count-i)
                stat = 30 if i < 24 or i == count else 20
                if sport == 'nba':
                    await conn.execute('''INSERT INTO nba_player_gamelogs(player_id,player_name,game_id,
                        game_date,season,team_abbreviation,opponent_team,is_home,points,source_provider,
                        source_sha256,source_record_sha256,source_observed_at)
                        VALUES($1,$2,$3,$4,$5,'BOS','LAL',TRUE,$6,'nba',$7,$7,$8)''',
                        player_id,player,f'{identity}{i:02}',game_date,season-1,stat,'a'*64,now)
                else:
                    row_season, week = season-2+i//17, i%17+1
                    await conn.execute('INSERT INTO games(game_id,season,week,home_team,away_team,game_date) VALUES($1,$2,$3,$4,$5,$6)',
                        f'{identity}{i:02}',row_season,week,'TST','OPP',game_date)
                    await conn.execute('''INSERT INTO player_stats(player_id,player_name,season,week,team,
                        passing_yards,source_provider,source_sha256,source_record_sha256,source_observed_at)
                        VALUES($1,$2,$3,$4,$5,$6,'nflverse',$7,$7,$8)''',
                        player_id,player,row_season,week,'TST',stat,'b'*64,now)
        result = await evaluate_event(pool,event,sport,ledger,identity)
        predictions = ledger.predictions()
        assert len(predictions) == 1
        assert result['coverage']['source_committed_quotes'] == result['coverage']['quotes'] == 1
        # Jeffreys posterior predictive mean for 24 Overs and no pushes.
        assert predictions[0]['model_probability'] == pytest.approx(24.5 / (count + 1), abs=1e-6)
        assert predictions[0]['push_probability'] == 0  # Integer stats cannot push at 20.5.
        async with pool.acquire() as conn:
            archived = await conn.fetchrow(
                'SELECT sport,game_id,player_name,side,line,price,snapped_at,game_start_time, '
                'source_provider,source_sha256,source_record_sha256 '
                'FROM player_prop_snapshots WHERE game_id=$1', identity)
        assert tuple(archived)[:6] == (sport,identity,player,'Over',20.5,100)
        assert archived['snapped_at'] == now
        assert archived['game_start_time'] == start
        expected_quote, = quotes_from_event(event,sport)
        assert archived['source_provider'] == 'the_odds_api'
        assert archived['source_sha256'] == expected_quote.source_sha256
        assert archived['source_record_sha256'] == expected_quote.source_record_sha256
        # NBA's 60% vs 50% quote passes policy; NFL's larger edge remains audited even if capped.
        if sport == 'nba':
            assert result['signals'][0]['sample_size'] == count
            assert result['signals'][0]['direction'] == 'over'
            assert result['signals'][0]['home_team']=='Boston Celtics'
        event['bookmakers'][0]['markets'][0]['outcomes'][0]['point'] = 20
        await evaluate_event(pool,event,sport,ledger,identity+'integer')
        integer = next(p for p in ledger.predictions() if p['line'] == 20)
        assert integer['push_probability'] == pytest.approx((count-24)/count, abs=1e-6)
    finally:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM player_prop_snapshots WHERE game_id=$1',identity)
            await conn.execute(f'DELETE FROM {table} WHERE player_id=$1',player_id)
            if sport == 'nfl':
                await conn.execute('DELETE FROM games WHERE game_id LIKE $1',identity+'%')
        await pool.close()
