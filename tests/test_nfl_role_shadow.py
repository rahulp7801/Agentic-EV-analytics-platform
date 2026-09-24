from copy import deepcopy
from datetime import datetime,timedelta,timezone
import gzip,json
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock
import pytest
from sportsbet.quant import nfl_role_shadow as role
from sportsbet.scan import quotes_from_event
from sportsbet.quant.market_baseline import paired_market_baseline
from sportsbet.ledger import Ledger

ROOT=Path(__file__).resolve().parents[1]

def fixture():
    now=datetime.now(timezone.utc);day='2026-09-24';start=datetime(2026,9,25,0,15,tzinfo=timezone.utc)
    # This retained-data fixture is evaluated at a fixed pregame instant after freeze.
    now=datetime.fromisoformat(role.FROZEN_AT)+timedelta(seconds=30)
    gsis='00-0032392';player=role.artifact()[1][gsis]
    raw=json.loads(gzip.decompress((ROOT/'docs/verification/2026-09-23-nfl-history-coverage-input.json.gz').read_bytes()))
    data=dict(observed_at=(now-timedelta(seconds=1)).isoformat(),cutoff=day,season_floor=2024,players=[player],
        stats=[r for r in raw['stats'] if r['stat']['player_id']==gsis],
        snaps=[r for r in raw['snaps'] if r['snap']['pfr_player_id']==player['pfr_player_id']])
    event=dict(id='role-test',home_team='Green Bay Packers',away_team='Atlanta Falcons',commence_time=start.isoformat(),bookmakers=[dict(key='book',markets=[dict(key='player_receptions',last_update=(now-timedelta(seconds=10)).isoformat(),outcomes=[dict(name=side,point=.5,price=-110,description=player['player']) for side in ('Over','Under')])])])
    quotes=quotes_from_event(event,'nfl');q=quotes[0]
    payload=dict(player=player['player'],player_id=gsis,sport='nfl',game_id=event['id'],home_team=event['home_team'],away_team=event['away_team'],
        game_date=day,game_start_time=start.isoformat(),forecast_cutoff=day,prop_type='receptions',line=.5,direction='over',
        sportsbook=q.sportsbook,american_odds=q.price,quote_time=q.snapped_at.isoformat(),quote_source_provider=q.source_provider,
        quote_source_sha256=q.source_sha256,quote_source_record_sha256=q.source_record_sha256,
        captured_at=now.isoformat(),model_generated_at=now.isoformat(),model_version='empirical-jeffreys-v4',
        model_sample_size=31,model_probability=.953125,model_mean_stat=2.19,push_probability=0,
        accepted=False,stake_fraction=0,gate_reason='stale_quote',**paired_market_baseline(q,quotes),
        availability=dict(status='observed',roster_confirmed=True,player_id=player['espn_player_id'],team='ATL',
            captured_at=now.isoformat(),roster_source_url='https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/1/roster',roster_source_sha256='a'*64))
    return payload,data


def test_exact_overlay_role_split_and_replay_preserve_baseline():
    p,data=fixture();before=deepcopy((p,data));record=role.shadow_record(p,data)
    assert record['status']=='predicted',record
    assert (p,data)==before
    assert record['counts']['sample_size']==35
    assert record['counts']['current_role_games']==2
    assert record['counts']['older_games']==33
    assert record['recovered_games']==4
    assert record['probability']==pytest.approx((1+20*(29.5/34))/22)
    assert role.verified_shadow_probability(p|{'role_history_shadow':record})==record['probability']
    changed=deepcopy(record);changed['counts']['current_role_games']=3
    assert role.verified_shadow_probability(p|{'role_history_shadow':changed}) is None
    assert role.verified_shadow_probability((p|{'availability':p['availability']|{'team':'GB'},'role_history_shadow':record})) is None


@pytest.mark.parametrize('fault',['missing_snap','wrong_player','late_input','early_input','wrong_cutoff','wrong_baseline','roster_id','roster_stale','integer_line','missing_stat'])
def test_incomplete_or_mismatched_inputs_abstain(fault):
    p,data=fixture()
    if fault=='missing_snap':data['snaps']=data['snaps'][1:]
    elif fault=='wrong_player':data['players']=[role.artifact()[1]['00-0037741']]
    elif fault=='late_input':data['observed_at']=(datetime.fromisoformat(p['captured_at'])+timedelta(seconds=1)).isoformat()
    elif fault=='early_input':data['observed_at']=(datetime.fromisoformat(p['captured_at'])-timedelta(seconds=301)).isoformat()
    elif fault=='wrong_cutoff':data['cutoff']='2026-09-25'
    elif fault=='wrong_baseline':p['model_probability']=.6
    elif fault=='roster_id':p['availability']['player_id']='999'
    elif fault=='roster_stale':p['availability']['captured_at']=(datetime.fromisoformat(p['captured_at'])-timedelta(hours=2)).isoformat()
    elif fault=='integer_line':p['line']=1
    elif fault=='missing_stat':data['stats']=data['stats'][1:]
    assert role.shadow_record(p,data)['status']=='unavailable'


def test_no_double_count_when_provider_later_recovers_a_row_and_conflicts_abstain():
    from sportsbet.ingestion.provenance import stat_row_sha256
    p,data=fixture();e=next(e for e in role.artifact()[2] if e['player_id']==p['player_id'])
    snap=e['source_evidence']['participation'];row=e['stat_row']|{k:data['stats'][0]['stat'][k] for k in role.PROVENANCE}
    row['source_record_sha256']=stat_row_sha256('nfl',row)
    data['stats'].append(dict(stat=row,game_date=e['game']['date'],game_id=snap['row']['game_id'],home_team=snap['home_team'],away_team=snap['away_team']))
    p.update(model_sample_size=32,model_probability=round(30.5/33,6),model_mean_stat=round(68/32,2))
    record=role.shadow_record(p,data);assert record['status']=='predicted',record
    assert record['counts']['sample_size']==35 and record['recovered_games']==3
    row['receptions']=1;row['receiving_yards']=1;row['source_record_sha256']=stat_row_sha256('nfl',row)
    assert role.shadow_record(p,data)['reason']=='conflicting_recovery'


def test_curve_is_monotone_and_side_probability_complements():
    p,data=fixture();base,rows,_=role.validated_rows(json.dumps(data,sort_keys=True,separators=(',',':')))
    curve=[role.probability(rows,'receptions',n+.5,2026,'ATL')[0] for n in range(10)]
    assert all(a>=b for a,b in zip(curve,curve[1:]))
    rec=role.shadow_record(p,data)
    # Complement alone cannot be forged without the opposite exact quote proof.
    changed=p|{'direction':'under','model_probability':1-p['model_probability']}
    assert role.shadow_record(changed,data)['status']=='unavailable'
    assert 0<rec['probability']<1


def test_late_ledger_receipt_is_owned_idempotent_and_atomic(tmp_path):
    p,data=fixture();p['role_history_shadow']=role.shadow_record(p,data)
    # Intentionally stale quote relative to the real ledger clock.
    ledger=Ledger(tmp_path/'role.sqlite',database_url='')
    key=ledger.record('role-test',p);row=next(r for r in ledger.predictions() if r['prediction_id']==key)
    assert row['role_history_shadow']['reason']=='invalid_or_late_recording'
    assert role.verified_recorded_shadow_probability(row) is None
    assert ledger.record('role-test',p)==key
    changed=deepcopy(p);changed['role_history_shadow']['probability']=.9
    with pytest.raises(ValueError,match='immutable'):ledger.record('role-test',changed)
    assert row['model_probability']==p['model_probability'] and row['accepted'] is False


@pytest.mark.asyncio
async def test_loader_uses_readonly_snapshot_and_exact_ids():
    p,data=fixture();conn=MagicMock();conn.fetch=AsyncMock(side_effect=[data['stats'],data['snaps']])
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    conn.transaction.return_value.__aenter__=AsyncMock()
    result=await role.load_inputs(pool,'nfl',2026,__import__('datetime').date(2026,9,24),{p['player_id'],'not-in-scope'})
    conn.transaction.assert_called_once_with(isolation='repeatable_read',readonly=True)
    assert list(result)==[p['player_id']]
    assert conn.fetch.call_args_list[0].args[1]==[p['player_id']]
    assert conn.fetch.call_args_list[1].args[1]==['HoopAu00']
    assert len(result[p['player_id']]['stats'])==31


def test_audit_retains_unavailable_denominator_and_never_promotes():
    from sportsbet.quant.nfl_role_shadow_audit import report_role_history_shadow
    p,data=fixture();p['prediction_id']='one';p['role_history_shadow']=role.shadow_record(p,data)
    p['role_history_shadow_recorded_at']=p['captured_at']
    report=report_role_history_shadow([p],'nfl')
    assert report['earliest_attempts']==1
    assert report['markets']['receptions']['counts']['valid_predictions']==1
    assert report['markets']['receptions']['status']=='insufficient_data'
    assert report['promote'] is False
