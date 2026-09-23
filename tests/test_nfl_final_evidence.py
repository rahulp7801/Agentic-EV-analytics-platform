import copy
import json
from datetime import datetime,timezone

import pytest

from sportsbet.ingestion.nfl_final_evidence import CORE,BASE,IDENTITY_URL,digest,inspect_bundle,plan_recovery
from sportsbet.ledger import Ledger,VERIFIED_SETTLEMENT_SOURCE

NOW=datetime(2026,9,23,tzinfo=timezone.utc)
EVENT='401872940';PLAYER='00-0036422';ESPN='3911853'
ROOT=f'{BASE}/events/{EVENT}/competitions/{EVENT}'


def source(url,data):
    text=json.dumps(data)
    return dict(url=url,response_text=text,sha256=digest(text),observed_at=NOW.isoformat())


def bundle():
    identity='gsis_id,espn_id\n'+PLAYER+','+ESPN+'\n'
    teams=[dict(id='7',homeAway='home',team=dict(displayName='Home',abbreviation='DEN')),
           dict(id='30',homeAway='away',team=dict(displayName='Away',abbreviation='JAX'))]
    summary=dict(header=dict(id=EVENT,season=dict(year=2026,type=2),week=2,league=dict(slug='nfl'),
        competitions=[dict(id=EVENT,date='2026-09-20T20:05Z',status=dict(type=dict(completed=True)),competitors=teams)]))
    stat_path=f'{ROOT}/competitors/7/roster/{ESPN}/statistics/0'
    entry=dict(playerId=int(ESPN),period=0,didNotPlay=False,valid=True,
        athlete={'$ref':f'https://{CORE}{BASE}/seasons/2026/athletes/{ESPN}'},
        statistics={'$ref':f'https://{CORE}{stat_path}'})
    stats={'$ref':f'https://{CORE}{stat_path}',
        'competition':{'$ref':f'https://{CORE}{ROOT}'},
        'athlete':entry['athlete'],
        'splits':dict(id='0',name='game',categories=[
            dict(name='general',stats=[dict(name='gamesPlayed',value=1.0)]),
            dict(name='receiving',stats=[dict(name='receptions',value=0.0),dict(name='receivingYards',value=0.0)])])}
    sources=[source(f'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={EVENT}',summary)]
    for tid in ('7','30'):
        path=f'{ROOT}/competitors/{tid}/roster'
        sources.append(source(f'https://{CORE}{path}?limit=100',{'$ref':f'https://{CORE}{path}','entries':[entry] if tid=='7' else []}))
    sources.append(source(f'https://{CORE}{stat_path}',stats))
    return dict(identity=dict(url=IDENTITY_URL,response_text=identity,source_sha256=digest(identity),retrieved_at=NOW.isoformat()),
        players=[dict(player_id=PLAYER,espn_event_id=EVENT,date='2026-09-20')],sources=sources)


def change(b,index,mutate):
    receipt=b['sources'][index];data=json.loads(receipt['response_text']);mutate(data)
    receipt.update(response_text=json.dumps(data),sha256=digest(json.dumps(data)))


def prediction(**changes):
    return dict(sport='nfl',game_id='odds-event',player='Adam Trautman',player_id=PLAYER,
        home_team='Home',away_team='Away',game_date='2026-09-20',
        game_start_time='2026-09-20T20:05:00Z',captured_at='2026-09-20T18:00:00Z',
        prop_type='receptions',direction='under',line=1.5,prediction_id='one',outcome=None,
        sportsbook='book',american_odds=-110,model_probability=.6)|changes


def test_explicit_zero_round_trips_through_existing_ledger_contract(tmp_path):
    evidence=inspect_bundle(bundle(),now=NOW);assert evidence[0]['stat_row']['receptions']==0
    ledger=Ledger(tmp_path/'audit.sqlite');p=prediction();p.pop('prediction_id');p.pop('outcome')
    key=ledger.record('scan',p);retained=ledger.predictions();before=copy.deepcopy(retained)
    plan=plan_recovery(retained,evidence);u,=plan['updates']
    assert retained==before and u['outcome'] is True
    ledger.settle({key:u['outcome']},source=VERIFIED_SETTLEMENT_SOURCE,source_ref=u['source_ref'],
        observed_at=NOW,actual_values={key:u['actual']},evidence={key:u['evidence']})
    assert ledger.report()['settled_count']==1
    assert plan_recovery(ledger.predictions(),evidence)['updates']==[]


@pytest.mark.parametrize(('direction','line','result'),[('over',.5,False),('under',.5,True),('under',0,'push')])
def test_zero_outcomes_use_original_direction_and_line(direction,line,result):
    p=prediction(direction=direction,line=line)
    assert plan_recovery([p],inspect_bundle(bundle(),now=NOW))['updates'][0]['outcome']==result


def test_dnp_is_never_zero_or_automatic_void():
    b=bundle();change(b,1,lambda d:d['entries'][0].update(didNotPlay=True,valid=False))
    b['sources'].pop()
    evidence=inspect_bundle(b,now=NOW)
    assert evidence[0]['status']=='did_not_play'
    assert plan_recovery([prediction()],evidence)==dict(updates=[],did_not_play_pending=['one'])


@pytest.mark.parametrize('changes',[
    dict(outcome=False),dict(home_team=None),dict(away_team='Other'),dict(player_id='00-0000001'),
    dict(game_start_time='2026-09-20T20:10:00Z'),dict(captured_at='2026-09-20T20:06:00Z'),
    dict(prop_type='pass_yds'),dict(line=-1),dict(sport='cfb')])
def test_recovery_does_not_change_unmatched_or_existing_results(changes):
    assert plan_recovery([prediction(**changes)],inspect_bundle(bundle(),now=NOW))['updates']==[]


@pytest.mark.parametrize(('index','mutate'),[
    (0,lambda d:d['header'].update(id='999')),
    (0,lambda d:d['header']['competitions'][0]['status']['type'].update(completed=False)),
    (0,lambda d:d['header']['season'].update(type=3)),
    (1,lambda d:d['entries'].append(copy.deepcopy(d['entries'][0]))),
    (1,lambda d:d['entries'][0].update(didNotPlay=None)),
    (1,lambda d:d['entries'][0].update(valid=False)),
    (1,lambda d:d['entries'][0]['statistics'].update({'$ref':'https://evil.example/stats'})),
    (3,lambda d:d['competition'].update({'$ref':f'https://{CORE}{ROOT}999'})),
    (3,lambda d:d['athlete'].update({'$ref':f'https://{CORE}{BASE}/seasons/2026/athletes/999'})),
    (3,lambda d:d['splits'].update(id='1')),
    (3,lambda d:d['splits']['categories'][0]['stats'][0].update(value=0)),
    (3,lambda d:d['splits']['categories'][1]['stats'][0].update(value=None)),
    (3,lambda d:d['splits']['categories'][1]['stats'][0].update(value=True)),
    (3,lambda d:d['splits']['categories'][1]['stats'][0].update(value=.5)),
    (3,lambda d:d['splits']['categories'][1]['stats'][0].update(value=-1)),
    (3,lambda d:d['splits']['categories'][1]['stats'][1].update(value=10)),
    (3,lambda d:d['splits']['categories'][1]['stats'].pop()),
    (3,lambda d:d['splits']['categories'].append(copy.deepcopy(d['splits']['categories'][1]))),
])
def test_invalid_explicit_evidence_fails_closed(index,mutate):
    b=bundle();change(b,index,mutate)
    with pytest.raises((ValueError,KeyError)):inspect_bundle(b,now=NOW)


@pytest.mark.parametrize('part',['source','identity','date','duplicate_source','duplicate_identity'])
def test_commitment_and_time_checks(part):
    b=bundle()
    if part=='source':b['sources'][0]['sha256']='0'*64
    if part=='identity':b['identity']['source_sha256']='0'*64
    if part=='date':b['sources'][0]['observed_at']='2026-09-19T00:00:00Z'
    if part=='duplicate_source':b['sources'].append(b['sources'][0])
    if part=='duplicate_identity':
        text=b['identity']['response_text']+PLAYER+',999\n'
        b['identity'].update(response_text=text,source_sha256=digest(text))
    with pytest.raises(ValueError):inspect_bundle(b,now=NOW)
