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
    return dict(id='test-event-'+sport,home_team='Home',away_team='Away',commence_time=(now+timedelta(hours=2)).isoformat(),
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
    pool=MagicMock()
    pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    quant=AsyncMock(return_value=PropResult(true_probability=Decimal('.6'),sample_size=40,mean_stat=Decimal('24')))
    target='sportsbet.prop.nba_agents.run_nba_prop_query' if sport=='nba' else 'sportsbet.prop.agents.run_prop_query'
    ledger=Ledger(tmp_path/'audit.sqlite')
    with patch(target,quant):
        result=await evaluate_event(pool,event(sport),sport,ledger,'scan')
    assert len(result['signals'])==2
    assert {s['direction'] for s in result['signals']}=={'over','under'}
    assert len(ledger.predictions())==2
    assert all(call.args[1].last_n_games==40 for call in quant.call_args_list)
    assert all(call.args[1].as_of_date is not None for call in quant.call_args_list)

def test_api_budget_survives_restart(tmp_path):
    path=tmp_path/'budget.sqlite'
    assert Ledger(path).reserve_api_credits(3,5)
    assert not Ledger(path).reserve_api_credits(3,5)
    assert Ledger(path).reserve_api_credits(2,5)
