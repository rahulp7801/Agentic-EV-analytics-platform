import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sportsbet.ledger import Ledger
from sportsbet.graph.models import PropResult,EVSignal
from sportsbet.scan import evaluate_event, quotes_from_event
from sportsbet.scan import recommendation_quality


async def test_strongest_uncertainty_margin_gets_correlated_risk_slot_first(tmp_path):
    raw=event('nfl')
    raw['bookmakers'][0]['markets'][0]['outcomes']=[
        dict(name='Over',description='Player',point=20.5,price=100),
        dict(name='Over',description='Player',point=21.5,price=100)]
    conn=AsyncMock();conn.fetch.return_value=[{'normalized_name':'player','player_id':'00-0037248'}]
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    now=datetime.now(timezone.utc)
    availability=dict(status='observed',captured_at=now.isoformat(),source_url='source',source_sha256='a'*64,
        teams=[dict(abbreviation='KC',roster_names=['Player'],roster_statuses={'Player':'Active'},
        roster_source_url='roster',roster_source_sha256='b'*64,reports=[])])
    async def result(_,params):
        strong=params.line==Decimal('21.5')
        return PropResult(true_probability=Decimal('.6' if strong else '.65'),sample_size=40,
            mean_stat=Decimal('24'),confidence_interval=(Decimal('.56'),Decimal('.64')) if strong
            else (Decimal('.52'),Decimal('.78')))
    ledger=Ledger(tmp_path/'quality.sqlite')
    with patch('sportsbet.prop.agents.run_prop_query',AsyncMock(side_effect=result)):
        output=await evaluate_event(pool,raw,'nfl',ledger,'quality',availability)
    accepted=[s for s in output['signals'] if not s['gated']]
    assert len(accepted)==1 and accepted[0]['line']==21.5 and accepted[0]['true_prob']==.6
    assert next(s for s in output['signals'] if s['line']==20.5)['gate_reason']=='correlated_exposure'
    assert len(ledger.predictions())==2  # Retain both immutable measured forecasts.
    assert all(p['recommendation_policy_version']=='lower-bound-margin-v1' for p in ledger.predictions())
    assert recommendation_quality(None)==(Decimal('-Infinity'),0)
    inconsistent=EVSignal(ev_percentage=Decimal('.1'),true_probability=Decimal('.6'),implied_probability=Decimal('.5'),
        kelly_fraction=Decimal('.01'),confidence_interval=(Decimal('.7'),Decimal('.8')),trade_plan=[],market_type='player_pass_yds')
    assert recommendation_quality(inconsistent)==(Decimal('-Infinity'),0)

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
    conn.fetch.return_value=[{'normalized_name':'player','player_id':'1'}]
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
    with patch(target,quant),patch.object(ledger,'record_many',wraps=ledger.record_many) as record_many:
        result=await evaluate_event(pool,event(sport),sport,ledger,'scan')
    record_many.assert_called_once()
    assert len(record_many.call_args.args[1])==2
    assert len(result['signals'])==2
    assert all(s['trade_plan'] and len(s['trade_plan'])==3 and s['gated']
        and s['gate_reason']=='availability_unavailable' and s['kelly_fraction']==0 for s in result['signals'])
    assert {s['direction'] for s in result['signals']}=={'over','under'}
    assert len(ledger.predictions())==2
    assert all(p['model_version']=='empirical-jeffreys-v4' and p['model_generated_at']==p['captured_at']
        and p['model_sample_size']==40 and len(p['model_confidence_interval'])==2
        and p['home_team']==event(sport)['home_team'] and p['away_team']==event(sport)['away_team']
        and p['quote_source_provider']=='the_odds_api'
        and len(p['quote_source_sha256'])==len(p['quote_source_record_sha256'])==64
        for p in ledger.predictions())
    assert {tuple(p['model_confidence_interval']) for p in ledger.predictions()}=={(.55,.65),(.35,.45)}
    assert result['coverage']['counts']['evaluated_selections']==2
    assert result['coverage']['unique_players']==result['coverage']['resolved_players']==1
    assert result['coverage']['model_requests']==2
    assert result['coverage']['model_estimates']==2
    assert result['coverage']['model_status']=='complete'
    assert result['coverage']['model_concurrency_limit']==8
    assert conn.fetch.await_count==1  # One batched identity lookup per event, not per player/line/side.
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
    conn=AsyncMock();conn.fetch.return_value=[{'normalized_name':'player','player_id':'1'}]
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


@pytest.mark.parametrize('injuries,expected',[(None,None),('Player','player_availability_risk'),
    ('Teammate','teammate_availability_unmodeled')])
@pytest.mark.parametrize('id_match',[False,True])
async def test_availability_really_controls_daily_recommendations(tmp_path,injuries,expected,id_match):
    conn=AsyncMock();conn.fetch.return_value=[{'normalized_name':'player','player_id':'00-0037248'}]
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    now=datetime.now(timezone.utc)
    roster_name='Player III' if id_match else 'Player'
    availability=dict(status='observed',captured_at=now.isoformat(),source_url='source',source_sha256='a'*64,
        teams=[dict(abbreviation='KC',roster_names=[roster_name,'Teammate'],roster_ids={'123':roster_name},
        roster_statuses={roster_name:'Active','Teammate':'Active'},roster_source_url='roster',roster_source_sha256='b'*64,reports=[] if injuries is None else
        [dict(player=roster_name if injuries=='Player' else injuries,status='Out',position='WR',reported_at=now.isoformat())])])
    if id_match:
        from sportsbet.prop.availability import NFL_PLAYER_IDS_URL
        availability.update(player_identities={'00-0037248':'123'},identity_source=dict(
            url=NFL_PLAYER_IDS_URL,source_sha256='c'*64,retrieved_at=now.isoformat()))
    result_model=PropResult(true_probability=Decimal('.6'),sample_size=40,mean_stat=Decimal('24'),
        confidence_interval=(Decimal('.55'),Decimal('.65')))
    ledger=Ledger(tmp_path/'audit.sqlite')
    with patch('sportsbet.prop.agents.run_prop_query',AsyncMock(return_value=result_model)),patch.object(ledger,'reserve',return_value=(True,'accepted')) as reserve:
        result=await evaluate_event(pool,event('nfl'),'nfl',ledger,'scan',availability)
    assert len(result['signals'])==2
    assert all(s['true_prob'] in [.6,.4] for s in result['signals'])
    if id_match:
        assert all(s['availability']['roster_player_name']==roster_name
            and s['availability']['probability_adjusted'] is False for s in result['signals'])
    if expected:
        reserve.assert_not_called()
        assert all(s['gate_reason']==expected and s['gated'] and s['kelly_fraction']==0 for s in result['signals'])
        assert all('Approved research stake at capture: 0.0%' in s['trade_plan'][1] for s in result['signals'])
    else:
        assert reserve.call_count==2 and all(not s['gated'] for s in result['signals'])


async def test_non_recommended_forecast_is_not_silently_discarded(tmp_path):
    conn=AsyncMock();conn.fetch.return_value=[{'normalized_name':'player','player_id':'1'}]
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    prop=PropResult(true_probability=Decimal('.5'),sample_size=40,mean_stat=Decimal('24'),
        confidence_interval=(Decimal('.3'),Decimal('.7')))
    with patch('sportsbet.prop.agents.run_prop_query',AsyncMock(return_value=prop)):
        result=await evaluate_event(pool,event('nfl'),'nfl',Ledger(tmp_path/'audit.sqlite'),'scan')
    assert len(result['signals'])==2
    assert all(s['gated'] and s['trade_plan'] and s['kelly_fraction']==0 for s in result['signals'])
