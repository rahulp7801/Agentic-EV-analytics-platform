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
        'status':'complete','captured_at':datetime.now(timezone.utc).isoformat(),'games':[]}))
    class Audit:
        def report(self,recommendations_only=False,model_version=None):
            return {'cohort':'recommendations' if recommendations_only else 'all_predictions',
                'model_version':model_version}
    monkeypatch.setattr(daily,'Ledger',Audit)
    monkeypatch.setattr(daily,'settle_final_props',lambda ledger,sport,schedule:{
        'sport':sport,'status':'complete','candidates':0,'settled':0,'pending':0,
        'reasons':{},'execution_ready':False})


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
    assert report['settlements']['nfl']['status']=='blocked'
    assert report['settlements']['nba']['status']=='complete'
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
    scan=AsyncMock();watch=AsyncMock(return_value=({'sources':{'kalshi':{'status':'observed','partial_coverage':False}},
        'captured_at':datetime.now(timezone.utc).isoformat()},None))
    monkeypatch.setattr(daily,'scan',scan);monkeypatch.setattr(daily,'watch',watch)
    result=await daily.run(['nfl'],'monitor',25)
    assert result['props']['nfl']['status']=='blocked'
    scan.assert_not_called()
    watch.assert_awaited_once_with('nfl',25,daily.DEFAULT_GAME_LIMIT,True)


@pytest.mark.asyncio
async def test_monitor_uses_recent_history_and_refreshes_markets_before_props(monkeypatch):
    monkeypatch.setattr(daily,'load_snapshot',lambda key:dict(status='complete',finished_at=datetime.now(timezone.utc).isoformat()))
    monkeypatch.setattr(daily,'publish_snapshot',lambda *args:None)
    watch=AsyncMock(return_value=({'sources':{'kalshi':{'status':'observed','partial_coverage':False}},
        'captured_at':datetime.now(timezone.utc).isoformat()},None))
    async def scan_ready(sports,limit):
        watch.assert_awaited_once_with('nba',25,daily.DEFAULT_GAME_LIMIT,True)
        return {'nba':{'status':'complete'}}
    scan=AsyncMock(side_effect=scan_ready)
    monkeypatch.setattr(daily,'scan',scan);monkeypatch.setattr(daily,'watch',watch)
    assert (await daily.run(['nba'],'monitor',25))['status']=='complete'
    scan.assert_awaited_once_with(['nba'],25)


@pytest.mark.asyncio
async def test_daily_settles_observed_stats_before_scanning_new_props(monkeypatch):
    calls=[];stored={}
    monkeypatch.setattr(daily,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    monkeypatch.setattr(daily,'refresh_history',lambda sport,day:(calls.append(('refresh',sport)) or {'status':'complete'}))
    monkeypatch.setattr(daily,'settle_final_props',lambda ledger,sport,schedule:
        (calls.append(('settle',sport)) or {'status':'complete','settled':1,'pending':0}))
    monkeypatch.setattr(daily,'watch',AsyncMock(return_value=({'sources':{'kalshi':{
        'status':'observed','partial_coverage':False}},'captured_at':datetime.now(timezone.utc).isoformat()},None)))
    async def scan(sports,limit):
        assert ('settle','nba') in calls
        calls.append(('scan','nba'))
        return {'nba':{'status':'complete'}}
    monkeypatch.setattr(daily,'scan',scan)
    result=await daily.run(['nba'],'daily',25)
    assert result['status']=='complete' and calls.index(('settle','nba'))<calls.index(('scan','nba'))
    assert stored['metrics:all']['cohort']=='all_predictions'
    assert stored['metrics:recommendations']['cohort']=='recommendations'
    assert stored['metrics:all']['model_version']==stored['metrics:recommendations']['model_version']=='empirical-jeffreys-v4'


@pytest.mark.asyncio
async def test_daily_uses_catchup_evidence_but_publishes_current_schedule_only(monkeypatch):
    stored={};settled=[]
    current={'status':'complete','captured_at':datetime.now(timezone.utc).isoformat(),
        'games':[{'label':'Yesterday'},{'label':'Today'},{'label':'Tomorrow'}],
        'failures':[],'sources':['current']}
    older={'status':'complete','captured_at':datetime.now(timezone.utc).isoformat(),
        'games':[{'label':'2026-09-05'}],'failures':[],'sources':['older']}
    collector=AsyncMock(side_effect=[current,older])
    monkeypatch.setattr(daily,'collect_schedule',collector)
    monkeypatch.setattr(daily,'pending_schedule_offsets',lambda ledger,sport,now:(-30,-8))
    monkeypatch.setattr(daily,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    monkeypatch.setattr(daily,'refresh_history',lambda *args:{'status':'complete'})
    monkeypatch.setattr(daily,'settle_final_props',lambda ledger,sport,schedule:
        (settled.append(schedule) or {'status':'complete','settled':0,'pending':0}))
    monkeypatch.setattr(daily,'watch',AsyncMock(return_value=({'sources':{'kalshi':{
        'status':'observed','partial_coverage':False}},'captured_at':datetime.now(timezone.utc).isoformat()},None)))
    monkeypatch.setattr(daily,'scan',AsyncMock(return_value={'nfl':{'status':'complete'}}))
    report=await daily.run(['nfl'],'daily',25)
    assert report['status']=='complete'
    assert collector.await_count==2
    current_call,older_call=collector.await_args_list
    assert current_call.args[0]=='nfl' and current_call.args[1] is older_call.args[1]
    assert current_call.kwargs=={}
    assert older_call.kwargs=={'offsets':(-30,-8,-7,-6,-5,-4,-3,-2)}
    assert [game['label'] for game in stored['schedule:nfl']['games']]==['Yesterday','Today','Tomorrow']
    assert [game['label'] for game in settled[0]['games']]==['2026-09-05','Yesterday','Today','Tomorrow']


@pytest.mark.asyncio
async def test_catchup_failure_degrades_settlement_without_hiding_current_schedule(monkeypatch):
    stored={};settled=[]
    current={'status':'complete','captured_at':datetime.now(timezone.utc).isoformat(),
        'games':[{'label':'Today'}],'failures':[],'sources':['current']}
    older={'status':'unavailable','captured_at':datetime.now(timezone.utc).isoformat(),
        'games':[],'failures':[{'date':'old'}],'sources':[]}
    monkeypatch.setattr(daily,'collect_schedule',AsyncMock(side_effect=[current,older]))
    monkeypatch.setattr(daily,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    monkeypatch.setattr(daily,'refresh_history',lambda *args:{'status':'complete'})
    monkeypatch.setattr(daily,'settle_final_props',lambda ledger,sport,schedule:
        (settled.append(schedule) or {'status':'degraded','settled':0,'pending':1}))
    monkeypatch.setattr(daily,'watch',AsyncMock(return_value=({'sources':{'kalshi':{
        'status':'observed','partial_coverage':False}},'captured_at':datetime.now(timezone.utc).isoformat()},None)))
    scan=AsyncMock(return_value={'nba':{'status':'complete'}});monkeypatch.setattr(daily,'scan',scan)
    report=await daily.run(['nba'],'daily',25)
    assert report['status']=='degraded' and report['schedules']['nba']['status']=='complete'
    assert stored['schedule:nba']==current and settled[0]['status']=='partial'
    scan.assert_awaited_once()


@pytest.mark.asyncio
async def test_settlement_failure_is_redacted_and_degrades_without_suppressing_scan(monkeypatch):
    monkeypatch.setattr(daily,'load_snapshot',lambda key:dict(
        status='complete',finished_at=datetime.now(timezone.utc).isoformat()))
    monkeypatch.setattr(daily,'publish_snapshot',lambda *args:None)
    monkeypatch.setattr(daily,'settle_final_props',lambda *args:(_ for _ in ()).throw(
        RuntimeError('provider URL with secret')))
    monkeypatch.setattr(daily,'watch',AsyncMock(return_value=({'sources':{'kalshi':{
        'status':'observed','partial_coverage':False}},'captured_at':datetime.now(timezone.utc).isoformat()},None)))
    scan=AsyncMock(return_value={'nba':{'status':'complete'}});monkeypatch.setattr(daily,'scan',scan)
    result=await daily.run(['nba'],'monitor',25)
    assert result['status']=='degraded' and result['settlements']['nba']=={
        'status':'failed','error_type':'RuntimeError'}
    assert 'secret' not in str(result)
    scan.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_monitor_real_collector_shares_budget_and_preserves_other_venues(monkeypatch,tmp_path):
    import json
    import httpx
    from sportsbet import market_watch
    ledger=Ledger(tmp_path/'credits.sqlite')
    stored={};requests=[]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings,'odds_api_key','fixture')
    monkeypatch.setattr(market_watch,'Ledger',lambda:ledger)
    monkeypatch.setattr(daily,'load_snapshot',lambda key:dict(status='complete',finished_at=datetime.now(timezone.utc).isoformat()))
    for module in (daily,market_watch):
        monkeypatch.setattr(module,'publish_snapshot',lambda key,value:stored.update({key:deepcopy(value)}))
    def provider(request):
        assert request.method=='GET' and request.url.host=='api.the-odds-api.com'
        requests.append(request)
        return httpx.Response(200,json=[])
    client=httpx.AsyncClient
    transport=httpx.MockTransport(provider)
    monkeypatch.setattr(httpx,'AsyncClient',lambda *args,**kwargs:client(*args,**(kwargs|{'transport':transport})))
    kalshi=AsyncMock(return_value={'status':'observed','games':[],'partial_coverage':False})
    prizepicks=AsyncMock(return_value={'projections':[],'partial_coverage':True})
    monkeypatch.setattr(market_watch,'kalshi_games',kalshi)
    monkeypatch.setattr(market_watch,'capture_projections',prizepicks)
    async def scan(sports,limit):
        assert len(requests)==1 and kalshi.await_count==prizepicks.await_count==2
        assert not ledger.reserve_api_credits(1,limit)  # Prop scans share the spent ceiling.
        return {sport:{'status':'budget_exhausted'} for sport in sports}
    monkeypatch.setattr(daily,'scan',scan)
    result=await daily.run(['nfl','nba'],'monitor',1)
    assert result['status']=='degraded' and len(requests)==1
    assert result['markets']['nfl']['sources']['sportsbook']['status']=='observed'
    assert result['markets']['nba']['sources']['sportsbook']['status']=='budget_exhausted'
    assert all(result['markets'][sport]['sources']['kalshi']['status']=='observed' for sport in ('nfl','nba'))
    archives=list((tmp_path/'.local/market-watch').glob('*.json'))
    assert len(archives)==2
    for path in archives:
        archive=json.loads(path.read_text())
        assert archive['summary']==stored['markets:'+archive['summary']['sport']]
        assert market_watch.comparisons(archive['evidence'])==archive['summary']['comparisons']


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
    assert result['scope']==daily.PUBLIC_SCOPES[mode]
    assert refreshed==(['nfl','nba'] if mode=='public_daily' else [])
    assert kalshi.await_count==2
    books.assert_not_called();prizepicks.assert_not_called();props.assert_not_called()
    assert all(value['status']=='not_requested' for value in result['props'].values())
    expected='complete' if mode=='public_daily' else 'not_requested'
    assert all(value['status']==expected for value in result['settlements'].values())
    if mode=='public_monitor':
        assert all(value['reason']=='monitor_mode' for value in result['settlements'].values())
        assert 'History refresh' in result['scope'] and 'not requested' in result['scope']
    else:
        assert 'history refresh' in result['scope'] and 'settlement evaluation' in result['scope']
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
