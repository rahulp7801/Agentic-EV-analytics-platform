from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from sportsbet import market_watch
from sportsbet.ledger import Ledger

HTTP_CLIENT=httpx.AsyncClient


@pytest.fixture
def collector(monkeypatch,tmp_path):
    stored={};requests=[]
    monkeypatch.setattr(market_watch.settings,'odds_api_key','test-key')
    ledger=Ledger(tmp_path/'credits.sqlite')
    monkeypatch.setattr(market_watch,'Ledger',lambda:ledger)
    monkeypatch.setattr(market_watch,'load_snapshot',lambda key:deepcopy(stored.get(key)))
    monkeypatch.setattr(market_watch,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    original=HTTP_CLIENT
    def handle(request):
        requests.append(request)
        assert request.method=='GET'
        return httpx.Response(200,json=[])
    monkeypatch.setattr(market_watch.httpx,'AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle)))
    return stored,requests,ledger


@pytest.mark.asyncio
async def test_six_hour_cadence_skips_both_paid_io_and_credit_reservation(monkeypatch,collector):
    stored,requests,ledger=collector
    assert (await market_watch.sportsbooks('nfl',25,cadence_hours=6))['status']=='observed'
    original=deepcopy(stored)
    result=await market_watch.sportsbooks('nfl',25,cadence_hours=6)
    assert result=={'status':'not_requested','reason':'collection_cadence','partial_coverage':True,'events':[]}
    assert len(requests)==1 and stored==original
    assert ledger.reserve_api_credits(24,25)  # Only one actual collection credit was spent.
    assert not ledger.reserve_api_credits(1,25)


@pytest.mark.asyncio
async def test_half_hourly_monitor_uses_eight_broad_credits_in_24_hours(monkeypatch,collector):
    _,requests,ledger=collector
    current=datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)
    monkeypatch.setattr(market_watch,'datetime',Clock)
    for _ in range(48):
        for sport in ('nfl','nba'):
            await market_watch.sportsbooks(sport,25,cadence_hours=6)
        current+=timedelta(minutes=30)
    assert len(requests)==8
    assert ledger.reserve_api_credits(17,25)
    assert not ledger.reserve_api_credits(1,25)


@pytest.mark.asyncio
@pytest.mark.parametrize('last',[None,'invalid','2026-09-17T12:00:00',True,'future','expired'])
async def test_bad_future_or_due_markers_cannot_block_capture(collector,last):
    stored,requests,_=collector
    now=datetime.now(timezone.utc)
    if last=='future':last=(now+timedelta(hours=1)).isoformat()
    if last=='expired':last=(now-timedelta(hours=6,seconds=1)).isoformat()
    stored['collection:sportsbook:nfl']={'attempted_at':last}
    assert (await market_watch.sportsbooks('nfl',25,cadence_hours=6))['status']=='observed'
    assert len(requests)==1


@pytest.mark.asyncio
async def test_leagues_have_independent_cadence_and_manual_capture_is_explicit(collector):
    _,requests,_=collector
    await market_watch.sportsbooks('nfl',25,cadence_hours=6)
    await market_watch.sportsbooks('nba',25,cadence_hours=6)
    await market_watch.sportsbooks('nfl',25)
    assert len(requests)==3


@pytest.mark.asyncio
async def test_budget_skip_does_not_create_a_fake_attempt_marker(collector):
    stored,requests,ledger=collector
    assert ledger.reserve_api_credits(25,25)
    result=await market_watch.sportsbooks('nfl',25,cadence_hours=6)
    assert result['status']=='budget_exhausted' and not stored and not requests


@pytest.mark.asyncio
async def test_provider_failure_is_spaced_out_and_charged_conservatively(monkeypatch,collector):
    stored,requests,ledger=collector
    original=HTTP_CLIENT
    def fail(request):
        requests.append(request)
        return httpx.Response(503)
    monkeypatch.setattr(market_watch.httpx,'AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(fail)))
    with pytest.raises(RuntimeError,match='Quote provider HTTP 503'):
        await market_watch.sportsbooks('nfl',25,cadence_hours=6)
    assert (await market_watch.sportsbooks('nfl',25,cadence_hours=6))['reason']=='collection_cadence'
    assert len(requests)==1 and ledger.reserve_api_credits(24,25)


@pytest.mark.asyncio
async def test_real_market_collector_retains_fresh_kalshi_when_books_are_deferred(monkeypatch,collector,tmp_path):
    stored,requests,_=collector
    monkeypatch.chdir(tmp_path)
    await market_watch.sportsbooks('nfl',25,cadence_hours=6)
    kalshi=AsyncMock(return_value={'status':'observed','games':[],'partial_coverage':False})
    monkeypatch.setattr(market_watch,'kalshi_games',kalshi)
    monkeypatch.setattr(market_watch,'capture_projections',AsyncMock(return_value={'projections':[]}))
    summary,_=await market_watch.run('nfl',25,1,True,sportsbook_cadence_hours=6)
    assert summary['sources']['sportsbook']=={'status':'not_requested','count':0,'partial_coverage':True,'reason':'collection_cadence'}
    assert summary['sources']['kalshi']['status']=='observed'
    assert 'kalshi-props:nfl' in stored and 'markets:nfl' in stored
    kalshi.assert_awaited_once()
    assert len(requests)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('hours',[True,-1,25,1.5,'6'])
async def test_invalid_cadence_is_rejected_before_collectors_run(hours):
    with pytest.raises(ValueError,match='Invalid sportsbook cadence'):
        await market_watch.run('nfl',25,1,True,sportsbook_cadence_hours=hours)


@pytest.mark.asyncio
async def test_cadence_requires_published_worker_state():
    with pytest.raises(ValueError,match='Invalid sportsbook cadence'):
        await market_watch.run('nfl',25,1,False,sportsbook_cadence_hours=6)
