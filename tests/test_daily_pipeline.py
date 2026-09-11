from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from sportsbet import daily
from sportsbet import refresh as refresh_module
from sportsbet.ledger import Ledger
from sportsbet.config import settings


@pytest.fixture(autouse=True)
def schedule_source(monkeypatch):
    monkeypatch.setattr(daily,'collect_schedule',AsyncMock(return_value={
        'status':'complete','captured_at':datetime.now(timezone.utc).isoformat()}))


@pytest.mark.asyncio
async def test_actual_daily_graph_isolates_refresh_failure_and_orders_paid_stages(monkeypatch):
    stored={}; calls=[]
    monkeypatch.setattr(daily,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    monkeypatch.setattr(refresh_module,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    def refresh(sport,day,backfill=False):
        calls.append(('refresh',sport))
        if sport=='nfl': raise RuntimeError('provider URL with secret')
    async def watch(sport,limit,count,publish):
        calls.append(('watch',sport))
        return {'sources':{'book':{'status':'observed'}},'captured_at':datetime.now(timezone.utc).isoformat()},None
    async def scan(sports,limit):
        assert sports==['nba']
        assert ('watch','nba') in calls and ('refresh','nba') in calls
        calls.append(('scan','nba'))
        return {'nba':{'status':'complete'}}
    monkeypatch.setattr(refresh_module,'refresh',refresh)
    monkeypatch.setattr(daily,'watch',watch)
    monkeypatch.setattr(daily,'scan',scan)
    report=await daily.run(['nfl','nba'],'daily',25)
    assert report['status']=='degraded'
    assert report['props']['nfl']['status']=='blocked'
    assert report['props']['nba']['status']=='complete'
    assert report['markets']['nba']['status']=='degraded'  # Unspecified coverage is not complete.
    assert stored['scan:nfl']['reason']=='history_refresh_unavailable'
    assert 'secret' not in str(report)
    assert report['execution_ready'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('status,hours',[('complete',40),('running',1),('failed',1),('complete',-1)])
async def test_monitor_cannot_use_old_failed_incomplete_or_future_refreshes(monkeypatch,status,hours):
    monkeypatch.setattr(daily,'load_snapshot',lambda key:dict(status=status,
        finished_at=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()))
    monkeypatch.setattr(daily,'publish_snapshot',lambda *args:None)
    scan=AsyncMock();watch=AsyncMock()
    monkeypatch.setattr(daily,'scan',scan);monkeypatch.setattr(daily,'watch',watch)
    result=await daily.run(['nfl'],'monitor',25)
    assert result['props']['nfl']['status']=='blocked'
    scan.assert_not_called();watch.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_uses_recent_history_without_paid_market_recollection(monkeypatch):
    monkeypatch.setattr(daily,'load_snapshot',lambda key:dict(status='complete',finished_at=datetime.now(timezone.utc).isoformat()))
    monkeypatch.setattr(daily,'publish_snapshot',lambda *args:None)
    scan=AsyncMock(return_value={'nba':{'status':'complete'}})
    watch=AsyncMock()
    monkeypatch.setattr(daily,'scan',scan);monkeypatch.setattr(daily,'watch',watch)
    assert (await daily.run(['nba'],'monitor',25))['status']=='complete'
    scan.assert_awaited_once_with(['nba'],25);watch.assert_not_called()


def test_rolling_credit_limit_includes_previous_days_and_survives_restart(monkeypatch,tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(settings,'odds_rolling_credit_limit',6)
    path=tmp_path/'budget.sqlite';ledger=Ledger(path)
    today=datetime.now(timezone.utc).date()
    with ledger.connect() as db:
        db.execute('INSERT INTO api_usage VALUES (?,?)',((today-timedelta(days=1)).isoformat(),5))
        db.execute('INSERT INTO api_usage VALUES (?,?)',((today-timedelta(days=31)).isoformat(),100))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:Ledger(path).reserve_api_credits(1,25),range(4)))
    assert sum(results)==1
    assert not Ledger(path).reserve_api_credits(1,25)
    assert not ledger.reserve_api_credits(True,25)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['public_daily','public_monitor'])
async def test_public_modes_use_real_graph_and_collector_without_paid_or_prop_calls(monkeypatch,tmp_path,mode):
    from sportsbet import market_watch
    stored={}; refreshed=[]
    monkeypatch.chdir(tmp_path)
    for module in (daily,refresh_module,market_watch):
        monkeypatch.setattr(module,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    def refresh(sport,day,backfill=False):
        refreshed.append(sport)
        return {'provider':'fixture'}
    monkeypatch.setattr(refresh_module,'refresh',refresh)
    def unexpected_read(*args):raise AssertionError('Public monitor must not load history or spend credits')
    monkeypatch.setattr(daily,'load_snapshot',unexpected_read)
    monkeypatch.setattr(Ledger,'reserve_api_credits',unexpected_read)
    books=AsyncMock();prizepicks=AsyncMock();props=AsyncMock()
    monkeypatch.setattr(market_watch,'sportsbooks',books)
    monkeypatch.setattr(market_watch,'capture_projections',prizepicks)
    monkeypatch.setattr(daily,'scan',props)
    kalshi=AsyncMock(return_value={'status':'observed','games':[],'partial_coverage':True})
    monkeypatch.setattr(market_watch,'kalshi_games',kalshi)
    result=await daily.run(['nfl','nba'],mode,25)
    assert result['status']=='observed' and result['execution_ready'] is False
    assert 'Public-only' in result['scope']
    assert refreshed==(['nfl','nba'] if mode=='public_daily' else [])
    assert kalshi.await_count==2
    books.assert_not_called();prizepicks.assert_not_called();props.assert_not_called()
    assert all(value['status']=='not_requested' for value in result['props'].values())
    assert not any(key.startswith('scan:') for key in stored)
    assert {'schedule:nfl','schedule:nba','markets:nfl','markets:nba','pipeline:'+mode}<=set(stored)
    for sport in ('nfl','nba'):
        assert result['markets'][sport]['sources']['kalshi']['partial_coverage'] is True
        assert result['markets'][sport]['sources']['sportsbook']['status']=='not_requested'
    assert len(list((tmp_path/'.local/market-watch').glob('*.json')))==2


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_stage',['markets','schedules','histories'])
async def test_public_failure_is_visible_without_suppressing_other_stages(monkeypatch,failed_stage):
    stored={}
    monkeypatch.setattr(daily,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    monkeypatch.setattr(daily,'refresh_history',lambda *args:{'status':'failed' if failed_stage=='histories' else 'complete'})
    monkeypatch.setattr(daily,'collect_schedule',AsyncMock(return_value={
        'status':'unavailable' if failed_stage=='schedules' else 'complete','captured_at':datetime.now(timezone.utc).isoformat()}))
    watch=AsyncMock(return_value=({'sources':{'kalshi':{'status':'unavailable' if failed_stage=='markets' else 'observed',
        'partial_coverage':True}},'captured_at':datetime.now(timezone.utc).isoformat()},None))
    monkeypatch.setattr(daily,'watch',watch)
    props=AsyncMock();monkeypatch.setattr(daily,'scan',props)
    result=await daily.run(['nfl','nba'],'public_daily',25)
    assert result['status']=='degraded'
    assert watch.await_count==2
    assert set(result['schedules'])==set(result['histories'])=={'nfl','nba'}
    props.assert_not_called()
    assert stored['pipeline:public_daily']['status']=='degraded'
