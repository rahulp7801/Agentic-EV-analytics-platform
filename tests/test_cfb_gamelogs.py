import asyncio
import io
import os
from datetime import date, datetime, timezone
from decimal import Decimal

import asyncpg
import httpx
import polars as pl
import pytest

from sportsbet.graph.models import PropParams
from sportsbet.ingestion.cfb_gamelogs import MAX_ASSET_BYTES, asset_urls, download_asset, normalize_assets
from sportsbet.prop.query_builder import PropQueryBuilder


def parquet(rows):
    buffer=io.BytesIO()
    pl.DataFrame(rows).write_parquet(buffer)
    return buffer.getvalue()


def fixtures(*,team_id=10):
    player=parquet([
        {'game_id':401,'season':2026,'team_id':team_id,'category':'passing','athlete_id':7,
         'athlete_name':'Exact Player','passingYards':'241','rushingYards':None,
         'receptions':None,'receivingYards':None},
        {'game_id':401,'season':2026,'team_id':team_id,'category':'rushing','athlete_id':7,
         'athlete_name':'Exact Player','passingYards':None,'rushingYards':'-3',
         'receptions':None,'receivingYards':None},
        {'game_id':401,'season':2026,'team_id':team_id,'category':'receiving','athlete_id':8,
         'athlete_name':'Other Player','passingYards':None,'rushingYards':None,
         'receptions':'6','receivingYards':'82'},
        {'game_id':401,'season':2026,'team_id':team_id,'category':'rushing','athlete_id':-1,
         'athlete_name':' Team ','passingYards':None,'rushingYards':'-4',
         'receptions':None,'receivingYards':None},
    ])
    schedule=parquet([{'game_id':401,'season':2026,'week':3,
        'game_date':'2026-09-12T19:30Z','home_id':10,'away_id':20,
        'home_team':'Home University','away_team':'Away State',
        'home_abbreviation':'HOM','away_abbreviation':'AWY','status':'STATUS_FINAL'}])
    return player,schedule


def test_cfb_assets_join_only_exact_ids_and_pivot_player_categories():
    player,schedule=fixtures()
    observed=datetime(2026,9,13,tzinfo=timezone.utc)
    rows,coverage=normalize_assets(player,schedule,2026,observed)
    assert len(rows)==2 and coverage['rows']==2 and coverage['skipped_team_aggregates']==1
    passer=next(row for row in rows if row['athlete_id']==7)
    assert (passer['passing_yards'],passer['rushing_yards'],passer['receiving_yards'])==(241,-3,None)
    assert passer['team_name']=='Home University' and passer['opponent_name']=='Away State'
    assert passer['is_home'] is True and passer['week']==3
    assert passer['source_observed_at']==observed
    assert all(len(passer[key])==64 for key in ('source_sha256','source_player_sha256',
        'source_schedule_sha256','source_record_sha256'))


def test_cfb_assets_reject_team_mismatch_and_bad_counts():
    player,schedule=fixtures(team_id=99)
    with pytest.raises(ValueError,match='does not match schedule'):
        normalize_assets(player,schedule,2026)
    player,schedule=fixtures()
    frame=pl.read_parquet(io.BytesIO(player)).with_columns(
        pl.when(pl.col('category')=='receiving').then(pl.lit('-1')).otherwise(pl.col('receptions')).alias('receptions'))
    buffer=io.BytesIO();frame.write_parquet(buffer)
    with pytest.raises(ValueError,match='negative CFB count'):
        normalize_assets(buffer.getvalue(),schedule,2026)


def test_cfb_release_urls_are_public_versioned_assets():
    assert asset_urls(2026)==(
        'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_player_box/player_box_2026.parquet',
        'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_schedules/cfb_schedule_2026.parquet')
    with pytest.raises(ValueError,match='season'):
        asset_urls(True)


def test_cfb_asset_download_bounds_redirect_hosts_and_bytes():
    def redirect(request):
        if request.url.host=='github.com':
            return httpx.Response(302,headers={'location':'https://release-assets.githubusercontent.com/file'})
        return httpx.Response(200,content=b'parquet')
    with httpx.Client(transport=httpx.MockTransport(redirect),follow_redirects=False) as client:
        assert download_asset(client,'https://github.com/release')==b'parquet'
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(
            302,headers={'location':'https://evil.example/file'})),follow_redirects=False) as client:
        with pytest.raises(ValueError,match='Untrusted'):
            download_asset(client,'https://github.com/release')
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(
            200,headers={'content-length':str(MAX_ASSET_BYTES+1)})),follow_redirects=False) as client:
        with pytest.raises(ValueError,match='response'):
            download_asset(client,'https://github.com/release')


def test_cfb_prop_query_uses_college_table_exact_id_and_cutoff():
    params=PropParams(game_id='future',player_id='4429000',season=2024,sport='cfb',
        prop_type='pass_yds',line=Decimal('250.5'),filters={},as_of_date=date(2026,9,20),last_n_games=40)
    sql,args=PropQueryBuilder.build(params)
    assert 'FROM cfb_player_gamelogs' in sql and 'athlete_id = CAST($1 AS bigint)' in sql
    assert 'game_date < $4' in sql and 'LIMIT $5' in sql
    assert args==(4429000,2024,250.5,date(2026,9,20),40)
    assert '4429000' not in sql and '250.5' not in sql
    for invalid_id in ('1 OR 1=1', '0', '9223372036854775808', '\u0661\u0662\u0663'):
        with pytest.raises(ValueError,match='CFB queries'):
            PropQueryBuilder.build(params.model_copy(update={'player_id':invalid_id}))


@pytest.mark.skipif(not os.environ.get('SPORTSBET_TEST_DATABASE_URL'),
    reason='Disposable PostgreSQL required')
def test_cfb_prop_query_binds_athlete_id_with_asyncpg():
    params=PropParams(game_id='future',player_id='4429000',season=2024,sport='cfb',
        prop_type='pass_yds',line=Decimal('250.5'),filters={},
        as_of_date=date(2026,9,20),last_n_games=40)
    sql,args=PropQueryBuilder.build(params)
    dsn=os.environ['SPORTSBET_TEST_DATABASE_URL'].replace('postgresql+psycopg://','postgresql://')

    async def query():
        conn=await asyncpg.connect(dsn)
        try:
            return await conn.fetchrow(sql,*args)
        finally:
            await conn.close()

    row=asyncio.run(query())
    assert isinstance(row['total'],int)
