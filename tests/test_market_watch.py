from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from sportsbet.ingestion.kalshi import KalshiReader
from sportsbet.market_watch import book_quotes, comparisons

NOW = datetime(2026,9,11,tzinfo=timezone.utc)


def evidence():
    event = dict(id='game',home_team='Home',away_team='Away',commence_time='2026-09-13T17:00:00Z',
        bookmakers=[dict(key='book',last_update=NOW.isoformat(),markets=[dict(key='h2h',outcomes=[
            dict(name='Home',price=110),dict(name='Away',price=110)])])])
    return dict(schema_version=2,sport='nfl',captured_at=NOW.isoformat(),sources={'sportsbook':{'events':[event]}})


def test_gross_price_gap_never_becomes_profit_or_verified_arbitrage():
    row, = comparisons(evidence())
    assert Decimal(row['gross_gap_to_one_dollar']) > 0
    assert row['status']=='unverified' and row['execution_ready'] is False
    assert row['realized_profit'] is None and row['fee_adjusted_profit'] is None
    assert 'tie/void' in row['reasons'][0]


@pytest.mark.parametrize('version',[0,3,True,'2'])
def test_unknown_or_malformed_evidence_version_is_not_reinterpreted(version):
    with pytest.raises(ValueError,match='Unsupported market evidence version'):
        comparisons(evidence()|{'schema_version':version})


def test_h2h_quotes_require_complete_teams_observation_time_and_current_window():
    event = evidence()['sources']['sportsbook']['events'][0]
    assert len(book_quotes(event,NOW))==2
    for invalid_time in ['2026-09-10T23:00:00Z','2026-09-11T01:00:00Z','2026-09-11T00:00:00']:
        changed=deepcopy(event)
        changed['bookmakers'][0]['last_update']=invalid_time
        assert book_quotes(changed,NOW)==[]
    changed=deepcopy(event)
    changed['commence_time']='2026-10-01T00:00:00Z'
    assert book_quotes(changed,NOW)==[]
    event['bookmakers'][0]['markets'][0]['outcomes'].append(dict(name='Draw',price=1000))
    assert book_quotes(event,NOW)==[]  # Cannot silently drop a third outcome.


@pytest.mark.asyncio
async def test_milestones_use_verified_league_filter_and_public_get():
    def handle(request):
        assert request.method=='GET' and request.url.params['competition']=='NFL'
        assert 'KALSHI-ACCESS-KEY' not in request.headers
        return httpx.Response(200,json={'milestones':[], 'cursor':''})
    async with KalshiReader(transport=httpx.MockTransport(handle)) as reader:
        assert (await reader.milestones('nfl',NOW))['milestones']==[]
        with pytest.raises(ValueError):
            await reader.milestones('nfl',NOW.replace(tzinfo=None))


def test_cross_venue_requires_unique_exact_team_and_start_match():
    data=evidence()
    snap=dict(market=dict(ticker='KX-TEST-H',title='Home wins',notional_value_dollars='1.0000',
        custom_strike={'football_team':'home'}),same_contract_pair=None,
        received_at=NOW.isoformat(),yes_asks=[('0.4','20')],no_asks=[])
    data['sources']['kalshi']=dict(targets={'home':{'name':'Home'},'away':{'name':'Away'}}, games=[dict(
        milestone=dict(title='Home vs Away',start_date='2026-09-13T17:00:00Z',
            details={'home_team_id':'home','away_team_id':'away'}),snapshots=[snap])])
    cross=[r for r in comparisons(data) if r['kind']=='kalshi_sportsbook']
    assert len(cross)==1 and cross[0]['legs'][1]['team']=='Away'
    assert cross[0]['execution_ready'] is False
    changed=deepcopy(data)
    changed['sources']['kalshi']['games'][0]['milestone']['start_date']='2026-09-13T18:00:00Z'
    assert not [r for r in comparisons(changed) if r['kind']=='kalshi_sportsbook']
    changed=deepcopy(data)
    changed['sources']['kalshi']['targets']['home']['name']='Home Other'
    assert not [r for r in comparisons(changed) if r['kind']=='kalshi_sportsbook']
    changed=deepcopy(data)
    duplicate=deepcopy(changed['sources']['sportsbook']['events'][0]);duplicate['id']='duplicate'
    changed['sources']['sportsbook']['events'].append(duplicate)
    assert not [r for r in comparisons(changed) if r['kind']=='kalshi_sportsbook']


def test_prop_handoff_keeps_only_normalized_worker_context_and_exact_team_aliases():
    from sportsbet import market_watch
    inventory={'quotes':[{'ticker':'PROP','player_target_id':'player'}],
        'targets':{'player':{'player_name':'Player'}},'coverage':{'structured_quote_markets':1}}
    source={'status':'observed','partial_coverage':False,'prop_inventory':inventory,
        'targets':{'home':{'name':'BOS','details':{'abbreviation':'BOS'}},
            'away':{'name':'LAL','details':{'abbreviation':'LAL'}}},
        'team_directory':{'sports':[{'leagues':[{'abbreviation':'NFL','teams':[
            {'team':{'abbreviation':'BOS','displayName':'Boston Team'}},
            {'team':{'abbreviation':'LAL','displayName':'Los Angeles Team'}}]}]}]},
        'games':[{'milestone':{'id':'game','start_date':'2026-09-13T17:00:00Z','details':{
            'main_game_event_ticker':'MAIN','home_team_id':'home','away_team_id':'away'}}}]}
    handoff=market_watch.kalshi_prop_handoff(source,'nfl',NOW.isoformat())
    assert handoff['status']=='observed' and handoff['execution_ready'] is False
    assert handoff['evidence']['quotes']==inventory['quotes']
    assert handoff['evidence']['player_targets']==inventory['targets']
    assert handoff['evidence']['games']==[{'milestone_id':'game',
        'scheduled_game_start_time':'2026-09-13T17:00:00+00:00','main_game_event_ticker':'MAIN',
        'home_team_id':'home','away_team_id':'away','home_team_aliases':['BOS','Boston Team'],
        'away_team_aliases':['LAL','Los Angeles Team']}]
    assert handoff['evidence_sha256']==market_watch.digest(handoff['evidence'])
    assert 'team_directory' not in handoff['evidence'] and 'targets' not in handoff['evidence']


@pytest.mark.asyncio
async def test_publish_writes_separate_prop_handoff_only_when_kalshi_is_requested(monkeypatch,tmp_path):
    from unittest.mock import AsyncMock
    from sportsbet import market_watch
    stored={};monkeypatch.chdir(tmp_path)
    source={'status':'observed','partial_coverage':False,'games':[],'targets':{},
        'prop_inventory':{'quotes':[],'targets':{},'coverage':{}}}
    monkeypatch.setattr(market_watch,'kalshi_games',AsyncMock(return_value=source))
    monkeypatch.setattr(market_watch,'publish_snapshot',lambda key,value:stored.update({key:value}))
    await market_watch.run('nfl',25,1,True,'kalshi')
    assert set(stored)=={'kalshi-props:nfl','markets:nfl'}
    assert stored['kalshi-props:nfl']['evidence_sha256']==market_watch.digest(
        stored['kalshi-props:nfl']['evidence'])
    stored.clear();monkeypatch.setattr(market_watch,'sportsbooks',AsyncMock(return_value={
        'status':'observed','events':[]}))
    await market_watch.run('nfl',25,1,True,'sportsbook')
    assert set(stored)=={'markets:nfl'}


@pytest.mark.asyncio
async def test_unavailable_source_is_retained_without_discarding_other_evidence(monkeypatch,tmp_path):
    from sportsbet import market_watch
    async def books(*args): return {'status':'observed','events':[]}
    async def kalshi(*args): return {'status':'observed','games':[]}
    async def blocked(*args): raise RuntimeError('provider URL could contain secrets')
    monkeypatch.setattr(market_watch,'sportsbooks',books)
    monkeypatch.setattr(market_watch,'kalshi_games',kalshi)
    monkeypatch.setattr(market_watch,'capture_projections',blocked)
    monkeypatch.chdir(tmp_path)
    report,path=await market_watch.run('nfl',25,1,False)
    assert path.exists()
    assert report['sources']['sportsbook']['status']=='observed'
    assert report['sources']['prizepicks']['status']=='unavailable'
    assert 'secrets' not in path.read_text()


def test_captured_event_fees_change_pair_and_cross_venue_costs_without_claiming_profit():
    data=evidence()
    market=dict(ticker='KX-TEST-H',title='Home wins',event_ticker='EVENT',notional_value_dollars='1.0000',
        custom_strike={'football_team':'home'},status='active',market_type='binary')
    snap=dict(market=market,same_contract_pair={'ask_cost':'0.96'},received_at=NOW.isoformat(),
        yes_asks=[('0.48','20')],no_asks=[('0.48','20')])
    fees=dict(status='observed',received_at=NOW.isoformat(),series=dict(ticker='KXNFLGAME',
        fee_type='quadratic',fee_multiplier=1,last_updated_ts=NOW.isoformat()),
        series_changes={'series_fee_change_arr':[]},event_changes={'cursor':'','event_fee_changes':[
            dict(event_ticker='EVENT',series_ticker='KXNFLGAME',fee_type_override='quadratic',fee_multiplier_override=2,
                scheduled_ts=NOW.isoformat())]})
    game=dict(event={'event':{'series_ticker':'KXNFLGAME'}},fee_context=fees,
        milestone=dict(title='Home vs Away',start_date='2026-09-13T17:00:00Z',details={
            'main_game_event_ticker':'EVENT','home_team_id':'home','away_team_id':'away'}),snapshots=[snap])
    data['sources']['kalshi']=dict(targets={'home':{'name':'Home'},'away':{'name':'Away'}},games=[game])
    rows=comparisons(data)
    pair=next(r for r in rows if r['kind']=='kalshi_pair')
    assert Decimal(pair['gross_cost'])<1
    assert Decimal(pair['exchange_fee_scenarios']['combined_cost']['direct'])>1
    assert [case['contracts_per_kalshi_leg'] for case in pair['depth_fee_scenarios']['cases']]==[1,10]
    assert all(Decimal(case['combined_cost']['direct'])>case['contracts_per_kalshi_leg']
        for case in pair['depth_fee_scenarios']['cases'])
    cross=[r for r in rows if r['kind']=='kalshi_sportsbook']
    assert len(cross)==2 and all('exchange_fee_scenarios' in r for r in cross)
    for row in cross:
        case=row['depth_fee_scenarios']['cases'][1]
        leg=next(iter(case['legs'].values()))
        assert Decimal(case['combined_cost']['direct'])==Decimal(leg['direct']['total_cost'])+10*Decimal(row['legs'][1]['cost'])
    legacy=deepcopy(data);legacy['schema_version']=1
    assert all('depth_fee_scenarios' not in r for r in comparisons(legacy))
    assert all(r['fee_adjusted_profit'] is None and r['execution_ready'] is False for r in rows)
    # An incomplete fee history must preserve gross observations but omit fee scenarios.
    fees['event_changes']['cursor']='more'
    assert all('exchange_fee_scenarios' not in r for r in comparisons(data))
    assert all('depth_fee_scenarios' not in r for r in comparisons(data))
    fees['event_changes']['cursor']=''
    market['fee_waiver_expiration_time']='2026-09-12T00:00:00Z'
    assert all('exchange_fee_scenarios' not in r for r in comparisons(data))
    del market['fee_waiver_expiration_time']
    snap['yes_asks']=[('0.48','0.5')]
    pair=next(r for r in comparisons(data) if r['kind']=='kalshi_pair')
    assert 'exchange_fee_scenarios' not in pair  # Cannot price a whole contract beyond displayed depth.
    assert pair['depth_fee_scenarios']['cases']==[]
    snap['yes_asks'].append(('0.6','10'))
    pair=next(r for r in comparisons(data) if r['kind']=='kalshi_pair')
    case=pair['depth_fee_scenarios']['cases'][0]
    assert len(case['legs']['yes']['direct']['modeled_fills'])==2
    assert Decimal(case['legs']['yes']['direct']['principal'])==Decimal('.54')


@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['sportsbook','kalshi','prizepicks'])
async def test_selected_provider_does_not_call_or_invent_coverage_for_others(monkeypatch,tmp_path,provider):
    from unittest.mock import AsyncMock
    from sportsbet import market_watch
    names={'sportsbook':'sportsbooks','kalshi':'kalshi_games','prizepicks':'capture_projections'}
    mocks={name:AsyncMock(return_value={'status':'observed','events':[],'games':[],'projections':[]}) for name in names}
    for name,attribute in names.items():monkeypatch.setattr(market_watch,attribute,mocks[name])
    monkeypatch.chdir(tmp_path)
    report,_=await market_watch.run('nfl',25,1,False,provider)
    for name,mock in mocks.items():
        if name==provider:
            mock.assert_awaited_once()
            assert report['sources'][name]['status']=='observed'
        else:
            mock.assert_not_called()
            assert report['sources'][name]['status']=='not_requested'
            assert report['sources'][name]['partial_coverage'] is True
    with pytest.raises(ValueError):await market_watch.run('nfl',25,1,False,'unknown')


@pytest.mark.parametrize('provider_status',['unavailable','budget_exhausted'])
def test_cli_reports_provider_failures_without_discarding_archives(monkeypatch,tmp_path,capsys,provider_status):
    import json
    from unittest.mock import AsyncMock
    from sportsbet import market_watch
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv',['market_watch','--sport','both','--provider','kalshi'])
    source=AsyncMock(return_value={'status':provider_status,'games':[]})
    monkeypatch.setattr(market_watch,'kalshi_games',source)
    with pytest.raises(SystemExit) as error:market_watch.main()
    assert error.value.code==2 and source.await_count==2
    reports=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r['sport'] for r in reports]==['nfl','nba']
    assert all(r['status']=='degraded' and r['comparisons']==0 for r in reports)
    assert len(list((tmp_path/'.local/market-watch').glob('*.json')))==2


def test_cli_distinguishes_valid_empty_coverage_and_isolates_league_errors(monkeypatch,tmp_path,capsys):
    import json
    from unittest.mock import AsyncMock
    from sportsbet import market_watch
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv',['market_watch','--sport','both','--provider','kalshi'])
    source=AsyncMock(return_value={'status':'observed','games':[],'partial_coverage':False})
    monkeypatch.setattr(market_watch,'kalshi_games',source)
    market_watch.main()  # Valid empty observations and intentionally unrequested sources succeed.
    reports=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(reports)==2 and all(r['status']=='observed' for r in reports)
    original=market_watch.run
    async def interrupted(sport,*args):
        if sport=='nfl':raise RuntimeError('database URL with a secret')
        return await original(sport,*args)
    monkeypatch.setattr(market_watch,'run',interrupted)
    with pytest.raises(SystemExit) as error:market_watch.main()
    assert error.value.code==2
    output=capsys.readouterr().out
    assert 'secret' not in output
    reports=[json.loads(line) for line in output.splitlines()]
    assert reports[0]['status']=='failed' and reports[0]['error_type']=='RuntimeError'
    assert reports[1]['sport']=='nba' and reports[1]['status']=='observed'


@pytest.mark.parametrize('mode',['match','mismatch','corrupt','publish'])
def test_replay_exit_status_rejects_mismatch_corruption_and_publishing(monkeypatch,tmp_path,capsys,mode):
    import json
    from sportsbet import market_watch
    evidence=dict(schema_version=2,sport='nfl',captured_at='2026-09-11T00:00:00Z',sources={})
    archive=dict(evidence=evidence,summary=dict(evidence_sha256=market_watch.digest(evidence),comparisons=[]))
    if mode=='mismatch':archive['summary']['comparisons']=[{'invalid':'saved result'}]
    if mode=='corrupt':archive['evidence']['sport']='nba'
    path=tmp_path/'capture.json'
    original=json.dumps(archive)
    path.write_text(original)
    def forbidden(*args,**kwargs):raise AssertionError('Replay must stay offline and preserve evidence')
    for name in ('run','publish_snapshot','write_archive'):
        monkeypatch.setattr(market_watch,name,forbidden)
    monkeypatch.setattr('sys.argv',['market_watch','--replay',str(path)]+(['--publish'] if mode=='publish' else []))
    if mode=='match':
        market_watch.main()
        assert json.loads(capsys.readouterr().out)['matches_archived_comparisons'] is True
    else:
        with pytest.raises(SystemExit) as error:market_watch.main()
        assert error.value.code!=0
        if mode=='mismatch':
            report=json.loads(capsys.readouterr().out)
            assert error.value.code==2 and report['matches_archived_comparisons'] is False
            assert report['execution_ready'] is False and report['realized_profit'] is None
    assert path.read_text()==original
