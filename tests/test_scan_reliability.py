from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from sportsbet import scan
from sportsbet.ledger import Ledger
from sportsbet.provider_cache import CachedResponse


@pytest.fixture
def worker(monkeypatch,tmp_path):
    stored={}
    class MemoryCache:
        def __init__(self):
            self.records={};self.leases={}
        def load(self,key,provider,sport,now):
            record=self.records.get(key)
            return record if record and record.expires_at>now else None
        def claim(self,key,provider,sport,owner,now,lease=None):
            if key in self.leases and self.leases[key]!=owner:return False
            self.leases[key]=owner;return True
        def store(self,key,provider,sport,owner,payload,captured_at,expires_at,release=True):
            assert self.leases.get(key)==owner
            self.records[key]=CachedResponse(deepcopy(payload),captured_at,expires_at)
            if release:self.leases.pop(key,None)
        def release(self,key,provider,sport,owner):
            if self.leases.get(key)==owner:self.leases.pop(key,None)
        def close(self):pass
    cache=MemoryCache()
    monkeypatch.setattr(scan,'ProviderResponseCache',lambda:cache)
    monkeypatch.setattr(scan.settings,'odds_api_key','test-key')
    monkeypatch.setattr(scan.settings,'analytics_database_url','test-configured')
    ledger=Ledger(tmp_path/'ledger.sqlite')
    monkeypatch.setattr(scan,'Ledger',lambda:ledger)
    monkeypatch.setattr(scan,'load_snapshot',lambda key:deepcopy(stored.get(key)))
    monkeypatch.setattr(scan,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    async def prior_batch(pool,sport,event_ids,now):
        return {event_id:scan.prior_event_evidence(sport,event_id,now) for event_id in event_ids}
    monkeypatch.setattr(scan,'prior_event_evidence_batch',prior_batch)
    pool=AsyncMock()
    pool.provider_cache=cache
    monkeypatch.setattr(scan,'create_async_pool',AsyncMock(return_value=pool))
    events={sport:[dict(id=sport+str(i),home_team='Home',away_team='Away',
        commence_time=(datetime.now(timezone.utc)+timedelta(hours=2+i)).isoformat()) for i in range(2)]
        for sport in ('nfl','nba')}
    evaluated=[]
    monkeypatch.setattr(scan,'fetch_event_availability',AsyncMock(return_value={'status':'unavailable'}))
    async def evaluate(pool,event,sport,ledger,scan_id,availability=None):
        evaluated.append(event['id'])
        return {'generated_at':datetime.now(timezone.utc).isoformat(),'signals':[], 'games':[],
            'coverage':{'quotes':0,'selections':0,'counts':{}}}
    monkeypatch.setattr(scan,'evaluate_event',evaluate)
    return stored,events,evaluated,pool


def transport(monkeypatch,handle):
    original=httpx.AsyncClient
    monkeypatch.setattr(scan.httpx,'AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle)))


async def test_future_forecasts_cover_48_hours_but_never_started_games(monkeypatch,worker):
    stored,events,evaluated,pool=worker
    now=datetime.now(timezone.utc)
    events['nfl']=[dict(id=identity,home_team='Home',away_team='Away',commence_time=(now+timedelta(hours=hours)).isoformat())
        for identity,hours in [('started',-1),('tomorrow',30),('too_far',49)]]
    def handle(request):
        if request.url.path.endswith('/events'):return httpx.Response(200,json=events['nfl'])
        return httpx.Response(200,json=events['nfl'][1])
    transport(monkeypatch,handle)
    await scan.run(['nfl'],4)
    assert evaluated==['tomorrow'] and stored['scan:nfl']['eligible_events']==1
    assert stored['scan:nfl']['events'][0]['game_id']=='tomorrow'
    assert stored['scan:nfl']['events'][0]['state']=='evaluated'


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
    for league in events.values():
        for event in league:
            event['commence_time']=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    # Raise the daily ceiling by exactly one event each run; prior credits remain spent.
    for limit in (4,7,11,14):
        await scan.run(['nfl','nba'],limit)
    assert evaluated==['nfl0','nba0','nfl1','nba1']
    assert stored['scan:nba']['completed_events']==1
    assert stored['scan:nba']['budget_skipped_events']==0
    assert stored['scan:nba']['cadence_deferred_events']==1
    assert stored['scan:nba']['status']=='scheduled'
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
    assert stored['metrics:all']['model_version']==stored['metrics:recommendations']['model_version']=='empirical-jeffreys-v4'
    assert stored['metrics:all:nfl']['sport']=='nfl' and stored['metrics:all:nba']['sport']=='nba'
    assert stored['metrics:recommendations:nfl']['sport']=='nfl'
    assert pool.close.await_count==4


@pytest.mark.asyncio
async def test_scarce_budget_refreshes_best_prior_near_pass_first(monkeypatch,worker):
    stored,events,evaluated,_=worker
    now=datetime.now(timezone.utc)
    for event in events['nba']:
        event['commence_time']=(now+timedelta(hours=2)).isoformat()
    candidate=dict(sample_size=30,true_prob=.62,implied_prob=.55,ev_pct=.07,push_probability=0,
        gate_reason='stale_quote',sportsbook='book',american_odds=-110,
        availability={'status':'observed','roster_confirmed':True})
    stored['signals:nba:nba0']={'signals':[candidate | dict(sport='nba',game_id='nba0',
        confidence_interval=[.525,.70])]}
    stored['signals:nba:nba1']={'signals':[candidate | dict(sport='nba',game_id='nba1',
        confidence_interval=[.54,.70])]}
    def handle(request):
        if request.url.path.endswith('/events'):return httpx.Response(200,json=events['nba'])
        identity=request.url.path.split('/')[-2]
        return httpx.Response(200,json=next(event for event in events['nba'] if event['id']==identity))
    transport(monkeypatch,handle)
    report=(await scan.run(['nba'],len(scan.MARKETS['nba'])))['nba']
    assert evaluated==['nba1']
    assert {event['game_id']:event['state'] for event in report['events']}=={
        'nba0':'api_budget','nba1':'evaluated'}


def test_prior_event_quality_rejects_malformed_and_weak_snapshots(monkeypatch):
    valid=dict(sport='nfl',game_id='event',sample_size=30,true_prob=.62,implied_prob=.55,
        ev_pct=.07,push_probability=0,confidence_interval=[.54,.70],
        gate_reason='stale_quote',sportsbook='book',american_odds=-110,
        availability={'status':'observed','roster_confirmed':True})
    snapshots={
        'signals:nfl:event':{'signals':[valid,valid | {'confidence_interval':[float('nan'),.7]}]},
        'signals:nfl:weak':{'signals':[valid | {'game_id':'weak','confidence_interval':[.50,.7]}]},
        'signals:nfl:huge':{'signals':[valid]*5001},
    }
    monkeypatch.setattr(scan,'load_snapshot',lambda key:deepcopy(snapshots.get(key)))
    assert scan.prior_event_quality('nfl','event')==pytest.approx((-.01,30))
    assert scan.prior_event_quality('nfl','weak') is None
    assert scan.prior_event_quality('nfl','huge') is None
    snapshots['signals:nfl:event']['signals'][0]['gate_reason']='edge_review_limit'
    assert scan.prior_event_quality('nfl','event')==pytest.approx((-.01,30))
    monkeypatch.setattr(scan,'load_snapshot',lambda key:(_ for _ in ()).throw(RuntimeError('offline')))
    assert scan.prior_event_quality('nfl','event') is None


@pytest.mark.asyncio
async def test_prior_event_batch_projects_bounded_fields_in_one_query():
    now=datetime.now(timezone.utc)
    valid=dict(sport='nfl',game_id='event',sample_size=30,true_prob=.62,implied_prob=.55,
        ev_pct=.07,push_probability=0,confidence_interval=[.54,.70],
        gate_reason='stale_quote',sportsbook='book',american_odds=-110,
        availability={'status':'observed','roster_confirmed':True})
    class Connection:
        async def fetch(self,sql,*args):
            assert 'jsonb_build_object' in sql and 'trade_plan' not in sql
            assert args==(['signals:nfl:event'],scan.MAX_PRIORITY_SIGNALS)
            return [dict(snapshot_key='signals:nfl:event',payload=json.dumps(dict(
                generated_at=now.isoformat(),games=[{'game_id':'event','sport':'nfl'}],
                signal_count=1,signals=[valid])))]
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    class Pool:
        def acquire(self): return Connection()
    result=await scan.prior_event_evidence_batch(Pool(),'nfl',['event'],now)
    quality,attempt=result['event']
    assert quality==pytest.approx((-.01,30)),result
    assert attempt==now.isoformat()

    class OfflineConnection(Connection):
        async def fetch(self,*args): raise RuntimeError('offline')
    class OfflinePool:
        def acquire(self): return OfflineConnection()
    assert await scan.prior_event_evidence_batch(OfflinePool(),'nfl',['event'],now)=={'event':(None,None)}


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
    assert {e['game_id']:e['state'] for e in report['events']}=={'nba0':'failed','nba1':'evaluated'}
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


@pytest.mark.asyncio
async def test_repeated_monitor_defers_network_requests_without_relabeling_old_quotes(monkeypatch,worker):
    stored,events,evaluated,pool=worker
    requests=[]
    def handle(request):
        requests.append(request.url.path)
        if request.url.path.endswith('/events'):return httpx.Response(200,json=events['nba'])
        return httpx.Response(200,json=next(e for e in events['nba'] if e['id'] in request.url.path))
    transport(monkeypatch,handle)
    await scan.run(['nba'],25)
    original=deepcopy(stored['signals:nba:nba0'])
    report=(await scan.run(['nba'],25))['nba']
    assert evaluated==['nba0','nba1']
    assert len(requests)==3  # One cached discovery request and just two paid event requests.
    assert report['status']=='scheduled' and report['cadence_deferred_events']==2
    assert report['next_refresh_at'] and report['completed_events']==0
    assert stored['signals:nba:nba0']==original  # No timestamp or eligibility rewrite.


@pytest.mark.asyncio
async def test_targeted_operator_scan_refreshes_one_exact_event_without_loosening_budget(monkeypatch,worker):
    stored,events,evaluated,_=worker
    requests=[]
    def handle(request):
        requests.append(request.url.path)
        if request.url.path.endswith('/events'):return httpx.Response(200,json=events['nba'])
        return httpx.Response(200,json=next(e for e in events['nba'] if e['id'] in request.url.path))
    transport(monkeypatch,handle)
    await scan.run(['nba'],25)
    report=(await scan.run(['nba'],25,frozenset({'nba1'})))['nba']
    assert evaluated==['nba0','nba1','nba1']
    assert requests.count('/v4/sports/basketball_nba/events/nba1/odds')==2
    assert report['eligible_events']==report['attempted_events']==report['completed_events']==1
    assert report['cadence_deferred_events']==report['budget_skipped_events']==0
    assert set(report['attempts'])=={'nba0','nba1'}
    with pytest.raises(ValueError,match='targeted'):
        await scan.run(['nfl','nba'],25,frozenset({'nba1'}))
    missing=(await scan.run(['nba'],25,frozenset({'missing'})))['nba']
    assert missing['status']=='degraded' and missing['eligible_events'] is None
    assert missing['failures']==[{'stage':'event_discovery','error_type':'ValueError'}]


@pytest.mark.asyncio
async def test_signal_snapshot_restores_lost_cadence_without_spending_again(monkeypatch,worker):
    stored,events,evaluated,_=worker
    now=datetime.now(timezone.utc)
    stored['signals:nba:nba0']={
        'generated_at':now.isoformat(),
        'signals':[],
        'games':[{'game_id':'nba0','sport':'nba'}],
    }
    def handle(request):
        if request.url.path.endswith('/events'):return httpx.Response(200,json=events['nba'])
        return httpx.Response(200,json=next(e for e in events['nba'] if e['id'] in request.url.path))
    transport(monkeypatch,handle)
    report=(await scan.run(['nba'],25))['nba']
    assert evaluated==['nba1']
    assert report['attempted_events']==report['completed_events']==1
    assert report['cadence_deferred_events']==1
    assert report['attempts']['nba0']==now.isoformat()


@pytest.mark.asyncio
async def test_scan_splits_reserved_checks_before_board_lock_and_final_hour(monkeypatch,worker):
    stored,events,evaluated,pool=worker
    assert scan.Ledger().reserve_api_credits(17,25)
    for event in events['nfl']:
        event['commence_time']=(datetime.now(timezone.utc)+timedelta(hours=3)).isoformat()
    def handle(request):
        if request.url.path.endswith('/events'):return httpx.Response(200,json=events['nfl'])
        return httpx.Response(200,json=next(e for e in events['nfl'] if e['id'] in request.url.path))
    transport(monkeypatch,handle)
    distant=(await scan.run(['nfl'],25))['nfl']
    assert distant['budget_skipped_events']==2 and not evaluated
    assert distant['budget_reasons']=={'pregame_credit_reserve':2}
    assert all(event['budget_reason']=='pregame_credit_reserve' for event in distant['events'])
    for event in distant['events']:
        assert scan.timestamp(event['next_reserve_release_at'])==scan.timestamp(event['game_start_time'])-scan.PRELOCK_QUOTE_WINDOW
    assert distant['attempted_events']==0
    for event in events['nfl']:
        event['commence_time']=(datetime.now(timezone.utc)+timedelta(minutes=90)).isoformat()
    pool.provider_cache.records.pop('odds:events:nfl')
    prelock=(await scan.run(['nfl'],25))['nfl']
    assert prelock['completed_events']==1 and prelock['budget_skipped_events']==1
    assert prelock['budget_reasons']=={'pregame_credit_reserve':1}
    deferred=next(event for event in prelock['events'] if event['state']=='api_budget')
    assert scan.timestamp(deferred['next_reserve_release_at'])==scan.timestamp(deferred['game_start_time'])-scan.LOCK_BEFORE_START
    assert evaluated==['nfl0']
    repeated=(await scan.run(['nfl'],25))['nfl']
    assert repeated['attempted_events']==0 and evaluated==['nfl0']
    for event in events['nfl']:
        event['commence_time']=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    pool.provider_cache.records.pop('odds:events:nfl')  # Provider schedule changed between synthetic runs.
    close=(await scan.run(['nfl'],25))['nfl']
    assert close['completed_events']==1 and close['budget_skipped_events']==0
    assert close['cadence_deferred_events']==1  # The other event was just captured.
    assert close['budget_reasons']=={}
    assert evaluated==['nfl0','nfl1']
    assert not scan.Ledger().reserve_api_credits(1,25)


@pytest.mark.asyncio
async def test_cfb_uses_its_own_manual_player_model_path(monkeypatch,worker):
    stored,events,evaluated,_=worker
    assert scan.SPORT_KEYS['cfb']=='americanfootball_ncaaf'
    events['cfb']=[dict(id='college1',home_team='Home College',away_team='Away College',
        commence_time=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat())]
    def handle(request):
        return httpx.Response(200,json=events['cfb'] if request.url.path.endswith('/events') else events['cfb'][0])
    transport(monkeypatch,handle)
    report=(await scan.run(['cfb'],25))['cfb']
    assert evaluated==['college1'] and report['completed_events']==1
    assert stored['signals:cfb:college1']['games']==[]


@pytest.mark.asyncio
async def test_prelock_event_precedes_distant_candidate_within_league(monkeypatch,worker):
    stored,events,evaluated,_=worker
    now=datetime.now(timezone.utc)
    events['nfl'][0]['commence_time']=(now+timedelta(hours=3)).isoformat()
    events['nfl'][1]['commence_time']=(now+timedelta(minutes=90)).isoformat()
    async def evidence(pool,sport,identities,now):
        return {'nfl0':((.2,40),None),'nfl1':(None,None)}
    monkeypatch.setattr(scan,'prior_event_evidence_batch',evidence)
    def handle(request):
        if request.url.path.endswith('/events'):return httpx.Response(200,json=events['nfl'])
        assert '/nfl1/' in request.url.path
        return httpx.Response(200,json=events['nfl'][1])
    transport(monkeypatch,handle)
    report=(await scan.run(['nfl'],4))['nfl']
    assert evaluated==['nfl1']
    assert report['completed_events']==report['budget_skipped_events']==1
    assert report['budget_reasons']=={'daily_credit_limit':1}
    assert all('next_reserve_release_at' not in event for event in report['events'])


@pytest.mark.asyncio
async def test_targeted_distant_scan_keeps_the_full_reserve(monkeypatch,worker):
    _,events,evaluated,_=worker
    for event in events['nfl']:
        event['commence_time']=(datetime.now(timezone.utc)+timedelta(hours=3)).isoformat()
    assert scan.Ledger().reserve_api_credits(11,20)
    def handle(request):
        assert request.url.path.endswith('/events')
        return httpx.Response(200,json=events['nfl'])
    transport(monkeypatch,handle)
    report=(await scan.run(['nfl'],20,frozenset({'nfl0'})))['nfl']
    assert report['budget_reasons']=={'pregame_credit_reserve':1}
    assert report['attempted_events']==0 and not evaluated
