import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sportsbet.ledger import Ledger
from sportsbet.graph.models import PropResult
from sportsbet.scan import evaluate_event, quotes_from_event

def event(sport='nba'):
    now=datetime.now(timezone.utc)
    market='player_points' if sport=='nba' else 'player_pass_yds'
    home,away=('Boston Celtics','Los Angeles Lakers') if sport=='nba' else ('Home','Away')
    return dict(id='test-event-'+sport,home_team=home,away_team=away,commence_time=(now+timedelta(hours=2)).isoformat(),
        bookmakers=[dict(key='book',last_update=now.isoformat(),markets=[dict(key=market,outcomes=[
            dict(name='Over',description='Player',point=20.5,price=100),dict(name='Under',description='Player',point=21.5,price=200)])])])

def test_quotes_require_real_timestamps_and_sides():
    raw=event()
    assert len(quotes_from_event(raw,'nba'))==2
    del raw['bookmakers'][0]['last_update']
    assert quotes_from_event(raw,'nba')==[]

@pytest.mark.parametrize('sport',['nba','nfl'])
async def test_scheduled_graph_routes_real_quotes_and_retains_recency(sport,tmp_path):
    conn=AsyncMock()
    conn.fetch.return_value=[{'player_id':1}]
    conn.fetchrow.return_value={'team_abbreviation':'BOS','game_date':datetime.now(timezone.utc).date()-timedelta(days=2)}
    pool=MagicMock()
    pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    both_started=asyncio.Event()
    started=0
    async def concurrent_quant(*args):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return PropResult(true_probability=Decimal('.6'),sample_size=40,mean_stat=Decimal('24'),
            confidence_interval=(Decimal('.55'),Decimal('.65')))
    quant=AsyncMock(side_effect=concurrent_quant)
    target='sportsbet.prop.nba_agents.run_nba_prop_query' if sport=='nba' else 'sportsbet.prop.agents.run_prop_query'
    ledger=Ledger(tmp_path/'audit.sqlite')
    with patch(target,quant):
        result=await evaluate_event(pool,event(sport),sport,ledger,'scan')
    assert len(result['signals'])==2
    assert {s['direction'] for s in result['signals']}=={'over','under'}
    assert len(ledger.predictions())==2
    assert all(p['model_version']=='empirical-jeffreys-v3' and p['model_generated_at']==p['captured_at']
        and p['quote_source_provider']=='the_odds_api'
        and len(p['quote_source_sha256'])==len(p['quote_source_record_sha256'])==64
        for p in ledger.predictions())
    assert result['coverage']['counts']['evaluated_selections']==2
    assert result['coverage']['unique_players']==result['coverage']['resolved_players']==1
    assert result['coverage']['model_requests']==2
    assert result['coverage']['model_estimates']==2
    assert result['coverage']['model_status']=='complete'
    assert result['coverage']['model_concurrency_limit']==8
    assert conn.fetch.await_count==1  # One identity lookup per player, not per line/side.
    assert all(call.args[1].last_n_games==40 for call in quant.call_args_list)
    assert all(call.args[1].as_of_date is not None for call in quant.call_args_list)
    if sport=='nba':
        assert all(call.args[1].opponent_team=='LAL' and call.args[1].home_away=='home'
            for call in quant.call_args_list)
        assert {signal['home_team'] for signal in result['signals']}=={'Boston Celtics'}
    conn.executemany.assert_awaited_once()
    statement, rows = conn.executemany.await_args.args
    assert 'INSERT INTO player_prop_snapshots' in statement
    assert len(rows)==2 and {row[9] for row in rows}=={'Over','Under'}


async def test_quote_archive_failure_blocks_unrecorded_model_output(tmp_path):
    conn=AsyncMock();conn.executemany.side_effect=RuntimeError('database URL with secret')
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    quant=AsyncMock(return_value=PropResult(true_probability=Decimal('.6'),sample_size=40))
    with patch('sportsbet.prop.nba_agents.run_nba_prop_query',quant):
        with pytest.raises(RuntimeError,match='database URL with secret'):
            await evaluate_event(pool,event(),'nba',Ledger(tmp_path/'audit.sqlite'),'scan')
    quant.assert_not_awaited()


async def test_graph_query_failure_cannot_be_reported_as_successful_empty_scan(tmp_path):
    conn=AsyncMock();conn.fetch.return_value=[{'player_id':1}]
    conn.fetchrow.return_value={'team_abbreviation':'BOS','game_date':datetime.now(timezone.utc).date()-timedelta(days=2)}
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    ledger=Ledger(tmp_path/'audit.sqlite')
    with patch('sportsbet.prop.nba_agents.run_nba_prop_query',side_effect=RuntimeError('unavailable')):
        with pytest.raises(RuntimeError,match='Model evaluation failed'):
            await evaluate_event(pool,event(), 'nba', ledger,'scan')
    assert ledger.predictions()==[]


async def test_unresolved_quoted_player_reports_unavailable_model_coverage(tmp_path):
    conn=AsyncMock();conn.fetch.return_value=[]
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    quant=AsyncMock(return_value=PropResult(true_probability=Decimal('.6'),sample_size=40))
    with patch('sportsbet.prop.nba_agents.run_nba_prop_query',quant):
        result=await evaluate_event(pool,event(),'nba',Ledger(tmp_path/'audit.sqlite'),'scan')
    assert result['signals']==[]
    assert result['coverage']['quotes']==2
    assert result['coverage']['selections']==2
    assert result['coverage']['model_requests']==result['coverage']['model_estimates']==0
    assert result['coverage']['model_status']=='unavailable'
    quant.assert_not_awaited()

def test_api_budget_survives_restart(tmp_path):
    path=tmp_path/'budget.sqlite'
    assert Ledger(path).reserve_api_credits(3,5)
    assert not Ledger(path).reserve_api_credits(3,5)
    assert Ledger(path).reserve_api_credits(2,5)
