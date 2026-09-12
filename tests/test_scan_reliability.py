from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from sportsbet import scan
from sportsbet.ledger import Ledger


@pytest.fixture
def worker(monkeypatch,tmp_path):
    stored={}
    monkeypatch.setattr(scan.settings,'odds_api_key','test-key')
    monkeypatch.setattr(scan.settings,'analytics_database_url','test-configured')
    ledger=Ledger(tmp_path/'ledger.sqlite')
    monkeypatch.setattr(scan,'Ledger',lambda:ledger)
    monkeypatch.setattr(scan,'load_snapshot',lambda key:deepcopy(stored.get(key)))
    monkeypatch.setattr(scan,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    pool=AsyncMock()
    monkeypatch.setattr(scan,'create_async_pool',AsyncMock(return_value=pool))
    events={sport:[dict(id=sport+str(i),home_team='Home',away_team='Away',
        commence_time=(datetime.now(timezone.utc)+timedelta(hours=2+i)).isoformat()) for i in range(2)]
        for sport in ('nfl','nba')}
    evaluated=[]
    async def evaluate(pool,event,sport,ledger,scan_id):
        evaluated.append(event['id'])
        return {'signals':[], 'games':[], 'coverage':{'quotes':0,'selections':0,'counts':{}}}
    monkeypatch.setattr(scan,'evaluate_event',evaluate)
    return stored,events,evaluated,pool


def transport(monkeypatch,handle):
    original=httpx.AsyncClient
    monkeypatch.setattr(scan.httpx,'AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle)))


@pytest.mark.asyncio
async def test_budget_rotation_covers_both_leagues_and_unseen_events(monkeypatch,worker):
    stored,events,evaluated,pool=worker
    def handle(request):
        assert request.method=='GET'
        sport='nba' if 'basketball' in request.url.path else 'nfl'
        if request.url.path.endswith('/events'): return httpx.Response(200,json=events[sport])
        identity=request.url.path.split('/')[-2]
        return httpx.Response(200,json=next(e for e in events[sport] if e['id']==identity))
    transport(monkeypatch,handle)
    # Raise the daily ceiling by exactly one event each run; prior credits remain spent.
    for limit in (4,7,11,14):
        await scan.run(['nfl','nba'],limit)
    assert evaluated==['nfl0','nba0','nfl1','nba1']
    assert stored['scan:nba']['completed_events']==1
    assert stored['scan:nba']['budget_skipped_events']==1
    assert stored['scan:nba']['status']=='degraded'
    assert stored['signals:nfl:nfl0']['cross_venue']['reason']=='missing_handoff'
    # The fourth scan attempted no NFL quote, so it replaces the prior screen with an honest empty snapshot.
    assert stored['prop-screens:nfl']['coverage']=={
        'events':0,'observed_events':0,'unavailable_events':0,'positive_gross_gaps':0,
        'sportsbook_gaps':0,'kalshi_sportsbook_gaps':0}
    assert stored['prop-screens:nfl']['execution_ready'] is False
    assert pool.close.await_count==4


@pytest.mark.asyncio
async def test_league_failure_does_not_stop_other_league_or_leak_provider_key(monkeypatch,worker):
    stored,events,evaluated,pool=worker
    def handle(request):
        if 'americanfootball' in request.url.path: return httpx.Response(401)
        if request.url.path.endswith('/events'): return httpx.Response(200,json=events['nba'])
        return httpx.Response(200,json=next(e for e in events['nba'] if e['id'] in request.url.path))
    transport(monkeypatch,handle)
    result=await scan.run(['nfl','nba'],25)
    assert evaluated==['nba0','nba1']
    assert result['nfl']['eligible_events'] is None
    assert result['nfl']['status']=='degraded'
    assert result['nba']['status']=='complete'
    assert 'test-key' not in str(stored)
    pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_mismatched_quote_response_is_rejected_and_next_event_continues(monkeypatch,worker):
    stored,events,evaluated,pool=worker
    def handle(request):
        if request.url.path.endswith('/events'): return httpx.Response(200,json=events['nba'])
        event=next(e for e in events['nba'] if e['id'] in request.url.path)
        return httpx.Response(200,json=event | ({'home_team':'Wrong'} if event['id']=='nba0' else {}))
    transport(monkeypatch,handle)
    report=(await scan.run(['nba'],25))['nba']
    assert evaluated==['nba1'] and report['completed_events']==1
    assert report['failures'][0]['event_id']=='nba0'
    assert 'nba0' in report['attempts']


@pytest.mark.parametrize('mode',['budget_exhausted','empty','provider_failure'])
def test_cli_status_matches_actual_scan_coverage(monkeypatch,worker,capsys,mode):
    import json
    stored,events,evaluated,pool=worker
    requests=[]
    def handle(request):
        requests.append(request)
        assert request.method=='GET' and request.url.path.endswith('/events')
        sport='nba' if 'basketball' in request.url.path else 'nfl'
        if mode=='provider_failure' and sport=='nfl':return httpx.Response(401)
        return httpx.Response(200,json=events[sport] if mode=='budget_exhausted' else [])
    transport(monkeypatch,handle)
    monkeypatch.setattr('sys.argv',['scan','--sport','both','--daily-credit-limit','1'])
    if mode=='empty':scan.main()
    else:
        with pytest.raises(SystemExit) as error:scan.main()
        assert error.value.code==2
    output=capsys.readouterr().out
    assert 'test-key' not in output
    reports=json.loads(output)
    assert len(requests)==2 and not evaluated
    for sport,report in reports.items():
        assert report['status']==stored['scan:'+sport]['status']
        if mode=='budget_exhausted':
            assert report['budget_skipped_events']==2 and report['failures']==[]
        elif mode=='empty':
            assert report['status']=='complete' and report['eligible_events']==0
    pool.close.assert_awaited_once()
