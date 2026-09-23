from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.graph.models import PropResult
from sportsbet.ledger import Ledger, quote_evidence_valid
from sportsbet.prop.availability import BASES, NFL_PLAYER_IDS_URL, nfl_roster_history_bindings
from sportsbet.scan import evaluate_event

GSIS='00-0037746'
NAME='Brian Robinson Jr.'


def availability(now):
    return dict(status='observed',captured_at=now.isoformat(),source_url=BASES['nfl']+'/injuries',
        source_sha256='a'*64,identity_source=dict(url=NFL_PLAYER_IDS_URL,source_sha256='b'*64,
        retrieved_at=now.isoformat()),player_identities={GSIS:'123'},
        teams=[dict(name=name,abbreviation=abbr,roster_ids={espn:player},roster_names=[player],
            roster_statuses={player:'Active'},reports=[],injury_coverage='observed',
            roster_source_url=BASES['nfl']+'/teams/'+team+'/roster',roster_source_sha256='c'*64)
            for name,abbr,team,espn,player in [('Home','KC','1','123',NAME),('Away','LV','2','456','Opponent')]])


def test_exact_roster_crosswalk_retains_source_binding():
    now=datetime.now(timezone.utc)
    data=availability(now)
    result=nfl_roster_history_bindings(data,dict(home_team='Home',away_team='Away'),now)
    assert set(result)=={NAME}
    assert result[NAME]['history_player_id']==GSIS
    assert result[NAME]['roster_player_id']=='123'
    assert result[NAME]['identity_source_sha256']=='b'*64
    assert result[NAME]['roster_source_sha256']=='c'*64
    assert 'Brian Robinson' not in result  # No suffix stripping or approximate matching.


@pytest.mark.parametrize('defect',['missing','stale','future','stale_crosswalk','wrong_source','bad_digest',
    'ambiguous_crosswalk','invalid_gsis','wrong_team','duplicate_team','wrong_roster_url',
    'bad_roster_digest','duplicate_roster_id','duplicate_roster_name','no_mapping','oversized_roster'])
def test_invalid_identity_evidence_cannot_supply_history(defect):
    now=datetime.now(timezone.utc);data=availability(now)
    if defect=='missing':data.pop('identity_source')
    elif defect=='stale':data['captured_at']=(now-timedelta(hours=2)).isoformat()
    elif defect=='future':data['captured_at']=(now+timedelta(minutes=2)).isoformat()
    elif defect=='stale_crosswalk':data['identity_source']['retrieved_at']=(now-timedelta(hours=2)).isoformat()
    elif defect=='wrong_source':data['identity_source']['url']='https://example.com/players.csv'
    elif defect=='bad_digest':data['identity_source']['source_sha256']='invalid'
    elif defect=='ambiguous_crosswalk':data['player_identities']['00-0000001']='123'
    elif defect=='invalid_gsis':data['player_identities']={'not-gsis':'123'}
    elif defect=='wrong_team':data['teams'][0]['name']='Other'
    elif defect=='duplicate_team':data['teams'][1]['name']='Home'
    elif defect=='wrong_roster_url':data['teams'][0]['roster_source_url']='https://example.com/roster'
    elif defect=='bad_roster_digest':data['teams'][0]['roster_source_sha256']='invalid'
    elif defect=='duplicate_roster_id':data['teams'][1]['roster_ids']={'123':'Other'}
    elif defect=='duplicate_roster_name':data['teams'][1]['roster_ids']={'456':NAME}
    elif defect=='no_mapping':data['player_identities']={}
    elif defect=='oversized_roster':data['teams'][0]['roster_ids']={str(i+1):f'Player {i}' for i in range(251)}
    assert NAME not in nfl_roster_history_bindings(data,dict(home_team='Home',away_team='Away'),now)


@pytest.mark.parametrize('case',['recovered','same_identity','conflicting_history','ambiguous_history',
    'missing_history','missing_crosswalk','duplicate_quote_names','out','teammate_out'])
async def test_scanner_resolves_only_authenticated_history_and_keeps_all_gates(tmp_path,monkeypatch,case):
    from sportsbet import scan
    monkeypatch.setattr(scan.settings,'history_shadow_enabled',False)
    now=datetime.now(timezone.utc);data=availability(now)
    raw=dict(id='identity-event',home_team='Home',away_team='Away',
        commence_time=(now+timedelta(hours=2)).isoformat(),bookmakers=[dict(key='book',last_update=now.isoformat(),
        markets=[dict(key='player_rush_yds',outcomes=[dict(name='Over',description=NAME,point=20.5,price=100)])])])
    rows=[dict(normalized_name='brian robinson',player_id=GSIS)]
    if case=='same_identity':rows.append(dict(normalized_name=NAME.lower(),player_id=GSIS))
    if case=='conflicting_history':rows.append(dict(normalized_name=NAME.lower(),player_id='00-0000001'))
    if case=='ambiguous_history':rows += [dict(normalized_name=NAME.lower(),player_id=id) for id in (GSIS,'00-0000001')]
    if case=='missing_history':rows=[]
    if case=='missing_crosswalk':data.pop('identity_source')
    if case=='duplicate_quote_names':
        raw['bookmakers'][0]['markets'][0]['outcomes'].append(dict(name='Over',description='Brian Robinson',point=20.5,price=100))
    if case in ('out','teammate_out'):
        data['teams'][0]['reports']=[dict(player=NAME if case=='out' else 'Teammate',position='RB',
            status='Out',reported_at=now.isoformat())]
    conn=AsyncMock();conn.fetch.return_value=rows
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock(return_value=None)
    estimate=PropResult(true_probability=Decimal('.6'),sample_size=40,mean_stat=Decimal('24'),
        confidence_interval=(Decimal('.55'),Decimal('.65')))
    ledger=Ledger(tmp_path/'identity.sqlite')
    with patch('sportsbet.prop.agents.run_prop_query',AsyncMock(return_value=estimate)) as quant, \
         patch('sportsbet.scan.historical_availability_splits',AsyncMock(return_value=[])), \
         patch('sportsbet.scan.load_ngs_evidence',AsyncMock(return_value=None)):
        result=await evaluate_event(pool,raw,'nfl',ledger,'identity-test',data)
    valid=case in ('recovered','same_identity','out','teammate_out')
    assert result['coverage']['resolved_players']==int(valid)
    assert conn.fetch.await_count==1
    if valid:
        quant.assert_awaited_once()
        assert quant.await_args.args[1].player_id==GSIS
        prediction=ledger.predictions()[0]
        assert prediction['player_id']==GSIS and prediction['player']==NAME
        assert prediction['player_identity_evidence']['history_player_id']==GSIS
        assert prediction['player_identity_evidence']['identity_source_url']==NFL_PLAYER_IDS_URL
        assert quote_evidence_valid(prediction)
        if case in ('out','teammate_out'):
            expected='player_availability_risk' if case=='out' else 'teammate_availability_unmodeled'
            assert result['signals'][0]['gate_reason']==expected and result['signals'][0]['gated']
        else:
            assert result['signals'][0]['gate_reason']=='accepted'
    else:
        quant.assert_not_awaited()
        assert ledger.predictions()==[]
        assert result['coverage']['counts']['unknown_or_ambiguous_player']>=1
