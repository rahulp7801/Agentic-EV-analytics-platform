from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from sportsbet import daily
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
    def refresh(sport,day):
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
    monkeypatch.setattr(daily,'refresh',refresh)
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
