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
            'sportsbook_gaps':0,'kalshi_sportsbook_gaps':0,'kalshi_fee_modeled':0,
            'kalshi_quotes':0,'kalshi_exact_markets':0,'kalshi_paired_sides':0,
            'kalshi_missing_ask_sides':0,'kalshi_missing_sportsbook_sides':0,
            'kalshi_observation_skew_sides':0,
            'kalshi_rule_terms_classified':0,
            'kalshi_direct_cost_below_one':0,'kalshi_non_direct_cost_below_one':0}
    assert stored['prop-screens:nfl']['execution_ready'] is False
    assert stored['metrics:all']['model_version']==stored['metrics:recommendations']['model_version']=='empirical-jeffreys-v3'
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


@pytest.mark.asyncio
async def test_unavailable_model_coverage_degrades_otherwise_completed_events(monkeypatch,worker):
    stored,events,_,_=worker
    async def unavailable(*args):
        return {'signals':[],'games':[],'coverage':{'quotes':2,'selections':2,
            'model_requests':0,'model_estimates':0,'model_status':'unavailable','counts':{}}}
    monkeypatch.setattr(scan,'evaluate_event',unavailable)
    def handle(request):
        if request.url.path.endswith('/events'): return httpx.Response(200,json=events['nba'])
        return httpx.Response(200,json=next(e for e in events['nba'] if e['id'] in request.url.path))
    transport(monkeypatch,handle)
    report=(await scan.run(['nba'],25))['nba']
    assert report['completed_events']==2
    assert report['model_complete_events']==report['model_partial_events']==0
    assert report['model_unavailable_events']==2
    assert report['status']=='degraded'
    assert stored['prop-screens:nba']['status']=='degraded'


@pytest.mark.asyncio
async def test_observed_quote_coverage_survives_model_failure(monkeypatch,worker):
    stored,events,_,_=worker
    now=datetime.now(timezone.utc)
    quoted=events['nba'][0] | {'bookmakers':[{'key':'book','last_update':now.isoformat(),
        'markets':[{'key':'player_points','outcomes':[
            {'name':'Over','description':'Player','point':20.5,'price':-110},
            {'name':'Under','description':'Player','point':20.5,'price':-110}]}]}]}
    events['nba']=[events['nba'][0]]
    monkeypatch.setattr(scan,'evaluate_event',AsyncMock(side_effect=TimeoutError))
    monkeypatch.setattr(scan,'screen_cross_venue',lambda *args:{'status':'observed','comparisons':[],
        'coverage':{'kalshi_quotes':3,'exact_markets':2,'side_funnel':{'paired':2,
            'missing_kalshi_ask':1,'missing_sportsbook_side':1,'observation_skew':0}}})
    def handle(request):
        return httpx.Response(200,json=events['nba'] if request.url.path.endswith('/events') else quoted)
    transport(monkeypatch,handle)
    report=(await scan.run(['nba'],25))['nba']
    assert report['status']=='degraded' and report['completed_events']==0
    assert report['failures']==[{'stage':'event_evaluation','event_id':'nba0','error_type':'TimeoutError'}]
    assert report['coverage']['nba0']['quotes']==2
    assert report['coverage']['nba0']['source_committed_quotes']==2
    assert report['coverage']['nba0']['model_status']=='pending'
    expected={'kalshi_quotes':3,'kalshi_exact_markets':2,'kalshi_paired_sides':2,
        'kalshi_missing_ask_sides':1,'kalshi_missing_sportsbook_sides':1,
        'kalshi_observation_skew_sides':0}
    coverage=stored['prop-screens:nba']['coverage']
    assert {key:coverage[key] for key in expected}==expected


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
