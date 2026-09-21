from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from sportsbet.prop.ngs_evidence import load_ngs_evidence


class _Context:
    def __init__(self, value): self.value=value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *args): return None


@pytest.mark.asyncio
async def test_ngs_evidence_uses_exact_game_week_and_only_prior_rows():
    conn=AsyncMock()
    conn.fetch=AsyncMock(return_value=[{'week':3}])
    conn.fetchrow=AsyncMock(return_value={
        'sample_weeks':4,'avg_separation':Decimal('2.71'),'avg_cushion':Decimal('5.3'),
        'avg_yac_above_expectation':Decimal('1.2'),'source_provider':'nflverse_ngs',
        'source_url':'https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_receiving.parquet',
        'source_sha256':'a'*64,'source_observed_at':datetime(2026,9,20,tzinfo=timezone.utc),
        'source_provider_count':1,'source_url_count':1,'source_version_count':1,
    })
    pool=MagicMock();pool.acquire.return_value=_Context(conn)
    result=await load_ngs_evidence(pool,player_gsis_id='00-0031234',season=2026,
        game_date=date(2026,9,20),team='LAR',prop_type='rec_yds')
    assert result and result['sample_weeks']==4 and result['cutoff_week']==3
    assert result['probability_adjusted'] is False
    assert result['metrics']['avg_separation']==2.71
    game_sql,*game_args=conn.fetch.await_args.args
    assert tuple(game_args)==(2026,date(2026,9,20),'LA') and 'game_date=$2' in game_sql
    evidence_sql,*evidence_args=conn.fetchrow.await_args.args
    assert tuple(evidence_args)==('00-0031234','receiving',2026,3)
    assert 'week < $4' in evidence_sql and 'season >= $3-1' in evidence_sql
    assert 'LIMIT 8' in evidence_sql and '00-0031234' not in evidence_sql


@pytest.mark.asyncio
async def test_ngs_evidence_fails_closed_without_unique_schedule_or_rows():
    conn=AsyncMock();conn.fetch=AsyncMock(return_value=[])
    pool=MagicMock();pool.acquire.return_value=_Context(conn)
    assert await load_ngs_evidence(pool,player_gsis_id='id',season=2026,
        game_date=date(2026,9,20),team='SEA',prop_type='pass_yds') is None
    conn.fetch.return_value=[{'week':2}]
    conn.fetchrow=AsyncMock(return_value={'sample_weeks':0})
    assert await load_ngs_evidence(pool,player_gsis_id='id',season=2026,
        game_date=date(2026,9,20),team='SEA',prop_type='pass_yds') is None
    assert await load_ngs_evidence(pool,player_gsis_id='id',season=2026,
        game_date=date(2026,9,20),team='SEA',prop_type='points') is None


@pytest.mark.asyncio
async def test_ngs_evidence_fails_closed_for_mixed_source_versions():
    conn=AsyncMock()
    conn.fetch=AsyncMock(return_value=[{'week':3}])
    conn.fetchrow=AsyncMock(return_value={
        'sample_weeks':2,'avg_separation':Decimal('2.5'),'avg_cushion':Decimal('5.0'),
        'avg_yac_above_expectation':Decimal('0.8'),'source_provider':'nflverse_ngs',
        'source_url':'https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_receiving.parquet',
        'source_sha256':'a'*64,'source_observed_at':datetime(2026,9,20,tzinfo=timezone.utc),
        'source_provider_count':1,'source_url_count':1,'source_version_count':2,
    })
    pool=MagicMock();pool.acquire.return_value=_Context(conn)
    assert await load_ngs_evidence(pool,player_gsis_id='00-0031234',season=2026,
        game_date=date(2026,9,20),team='LAR',prop_type='rec_yds') is None
