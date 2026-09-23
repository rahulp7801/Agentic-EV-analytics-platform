from __future__ import annotations

from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock
from zoneinfo import ZoneInfo
import json
import math

import numpy as np
import pytest

from sportsbet.ledger import Ledger
from sportsbet.quant import history_shadow as shadow
from sportsbet.quant import history_shadow_audit as audit
from sportsbet.quant.history_features import history_estimates
from sportsbet.quant.history_tuning import build_examples
from sportsbet.quant.market_baseline import paired_market_baseline
from sportsbet.scan import quotes_from_event


def fixture(sport='nfl',prop='rec_yds',side='over',line=None,now=None):
    now=now or datetime.now(timezone.utc)
    start=now+timedelta(days=1)
    target=start.astimezone(ZoneInfo('America/New_York')).date()
    season=target.year if target.month>=(10 if sport=='nba' else 9) else target.year-1
    player='1' if sport=='nba' else '00-1'
    stat,workload,_=shadow.MARKETS[sport][prop]
    rows=[dict(player=player,player_id=int(player) if sport=='nba' else player,game=f'prior-{i}',
        day=target-timedelta(days=(40-i)*(2 if sport=='nba' else 7)),season=season,team='HOM',
        **{stat:10+i%9 if sport=='nba' else 30+i%20,workload:20+i%5 if sport=='nba' else 4+i%3})
        for i in range(40)]
    if line is None: line=13.5 if sport=='nba' else 39.5
    estimate=history_estimates(rows,stat,workload,target,line)
    market={'rec_yds':'player_reception_yds','receptions':'player_receptions',
        'points':'player_points','rebounds':'player_rebounds','assists':'player_assists'}[prop]
    event=dict(id='event',home_team='Home',away_team='Away',commence_time=start.isoformat(),
        bookmakers=[dict(key='book',last_update=(now-timedelta(seconds=10)).isoformat(),markets=[dict(
            key=market,last_update=(now-timedelta(seconds=10)).isoformat(),outcomes=[dict(
                name=direction,description='Player',point=line,price=-110) for direction in ('Over','Under')])])])
    quotes=quotes_from_event(event,sport)
    q=next(q for q in quotes if q.side.lower()==side)
    p=estimate['base'] if side=='over' else 1-estimate['base']
    payload=dict(game_id='event',player='Player',player_id=player,sport=sport,game_date=target.isoformat(),
        home_team='Home',away_team='Away',prop_type=prop,direction=side,line=line,sportsbook=q.sportsbook,
        american_odds=q.price,model_probability=round(p,6),push_probability=0,model_sample_size=40,
        model_mean_stat=round(estimate['mean'],2),forecast_cutoff=target.isoformat(),
        captured_at=now.isoformat(),game_start_time=start.isoformat(),quote_time=q.snapped_at.isoformat(),
        model_generated_at=now.isoformat(),quote_source_provider=q.source_provider,
        quote_source_sha256=q.source_sha256,quote_source_record_sha256=q.source_record_sha256,
        accepted=False,stake_fraction=0,model_version='empirical-jeffreys-v4',gate_reason='no_positive_edge',
        **paired_market_baseline(q,quotes))
    return payload,rows,event


@pytest.mark.parametrize(('sport','prop'),[(s,p) for s,markets in shadow.MARKETS.items() for p in markets])
def test_frozen_artifact_exactly_matches_selected_research_coefficients(sport,prop):
    report=json.loads(Path('docs/verification/2026-09-23-history-tuning-results.json').read_text())
    result=report['sports'][sport]['props'][prop]
    assert result['shadow_research_supported']
    assert shadow.parameters(sport,prop)=={'candidate':result['selected'],
        **result['fitted_corrections'][result['selected']]}
    assert shadow.digest(shadow.ARTIFACT)==shadow.ARTIFACT_SHA256
    payload,rows,_=fixture(sport,prop)
    recorded=shadow.shadow_record(payload,rows)
    assert recorded['status']=='predicted',recorded
    assert shadow.verified_shadow_probability(payload|{'history_shadow':recorded})==recorded['probability']


def test_shared_feature_formula_matches_original_frozen_formula_and_research_examples():
    payload,rows,_=fixture('nba','points',now=datetime(2025,2,1,tzinfo=timezone.utc))
    target=date.fromisoformat(payload['game_date'])
    # Independent arithmetic from the original, before extraction to a shared helper.
    values=np.asarray([r['points'] for r in rows]);hits=values>13.5
    base=(hits.sum()+.5)/41
    logit=lambda p:math.log(p/(1-p))
    work=math.log((np.mean([r['minutes'] for r in rows[-5:]])+1)/(np.mean([r['minutes'] for r in rows])+1))
    expected=(logit(base),logit((hits[-5:].sum()+.5)/6)-logit(base),
        logit((hits[-10:].sum()+.5)/11)-logit(base),
        (values[-5:].mean()-values.mean())/max(1,values.std()),work,math.log1p(2),0)
    assert history_estimates(rows,'points','minutes',target,13.5)['features']==pytest.approx(expected,abs=1e-14)
    target_row=rows[-1]|dict(game='target',day=target,points=99,minutes=99,team='FUTURE')
    examples,_=build_examples(rows+[target_row],'nba','points')
    for example in [e for e in examples if e.game=='target']:
        assert example.features==history_estimates(rows,'points','minutes',target,example.line)['features']


@pytest.mark.parametrize(('change','reason'),[
    ({'line':40.0},'unsupported_line'),({'line':40.2},'unsupported_line'),
    ({'model_sample_size':39},'baseline_history_mismatch'),
    ({'model_probability':.8},'baseline_history_mismatch'),
    ({'model_mean_stat':100},'baseline_history_mismatch'),
    ({'forecast_cutoff':'2020-01-01'},'unsupported_baseline'),
    ({'push_probability':.1},'unsupported_baseline'),
    ({'quote_source_record_sha256':'a'*64},'invalid_exact_offer'),
])
def test_invalid_or_nonmatching_inputs_have_explicit_skip_reasons(change,reason):
    p,rows,_=fixture()
    assert shadow.shadow_record(p|change,rows)['reason']==reason


@pytest.mark.parametrize('mutation',['target_day','future','identity','duplicate','missing','negative_workload','low_workload','commitment'])
def test_history_cutoff_identity_workload_and_source_fail_closed(mutation):
    p,rows,_=fixture()
    if mutation=='target_day':rows[-1]['day']=date.fromisoformat(p['game_date'])
    if mutation=='future':rows[-1]['day']=date.fromisoformat(p['game_date'])+timedelta(days=1)
    if mutation=='identity':rows[-1]['player']='wrong'
    if mutation=='duplicate':rows[-1]['game']=rows[0]['game']
    if mutation=='missing':rows[-1]['targets']=None
    if mutation=='negative_workload':rows[-1]['targets']=-1
    if mutation=='low_workload':
        for row in rows[-5:]:row['targets']=0
    if mutation=='commitment':rows[-1]['source_record_sha256']='a'*64
    assert shadow.shadow_record(p,rows)['status']=='unavailable'
    assert shadow.shadow_record(p,rows[:19])['reason']=='insufficient_history'


def test_quote_age_postgame_prefreeze_and_feature_outliers_are_excluded():
    now=datetime.now(timezone.utc)
    p,rows,_=fixture(now=now-timedelta(seconds=400))
    p.update(captured_at=now.isoformat(),model_generated_at=now.isoformat())
    assert shadow.shadow_record(p,rows)['reason']=='outside_prospective_quote_window'
    p,rows,_=fixture(now=datetime(2026,9,22,tzinfo=timezone.utc))
    assert shadow.shadow_record(p,rows)['reason']=='outside_prospective_quote_window'
    p,rows,_=fixture()
    for row in rows:row['day']-=timedelta(days=300)
    assert shadow.shadow_record(p,rows)['reason']=='outside_frozen_feature_range'


def test_probability_complements_monotonicity_and_tamper_detection():
    now=datetime.now(timezone.utc);probabilities=[]
    for line in (30.5,35.5,39.5,45.5,49.5):
        p,rows,_=fixture(line=line,now=now);q,_,_=fixture(line=line,side='under',now=now)
        over=shadow.shadow_record(p,rows);under=shadow.shadow_record(q,rows)
        assert over['probability']+under['probability']==pytest.approx(1)
        probabilities.append(over['probability'])
    assert probabilities==sorted(probabilities,reverse=True)
    p,rows,_=fixture();p['history_shadow']=shadow.shadow_record(p,rows)
    for key,value in [('probability',.9),('history_sha256','a'*64),('features',[0]*7),('artifact_sha256','b'*64)]:
        changed=deepcopy(p);changed['history_shadow'][key]=value
        assert shadow.verified_shadow_probability(changed) is None
    changed=p|{'sportsbook':'different'}
    assert shadow.verified_shadow_probability(changed) is None


def test_nonmonotone_candidate_cannot_be_recorded(monkeypatch):
    p,rows,_=fixture()
    monkeypatch.setattr(shadow,'predicted_over',lambda features,params,**kwargs:1/(1+math.exp(features[0])))
    assert shadow.shadow_record(p,rows)['reason']=='nonmonotone_candidate'


def test_immutable_storage_keeps_primary_values_and_rejects_late_shadow(tmp_path,monkeypatch):
    p,rows,_=fixture();original=deepcopy(p);p['history_shadow']=shadow.shadow_record(p,rows)
    ledger=Ledger(tmp_path/'shadow.sqlite');key=ledger.record('capture',p)
    stored=ledger.predictions()[0]
    assert shadow.verified_recorded_shadow_probability(stored)==p['history_shadow']['probability']
    assert shadow.verified_recorded_shadow_probability(p) is None
    assert datetime.fromisoformat(stored['history_shadow_recorded_at'])>=datetime.fromisoformat(p['captured_at'])
    assert all(stored[k]==v for k,v in original.items())
    assert ledger.record('capture',p)==key
    changed=deepcopy(p);changed['history_shadow']['probability']=.123
    with pytest.raises(ValueError,match='immutable'):ledger.record('capture',changed)
    class AfterKickoff(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromisoformat(p['game_start_time'])+timedelta(seconds=1)
    monkeypatch.setattr('sportsbet.ledger.datetime',AfterKickoff)
    ledger.record('late',p)
    late=next(r for r in ledger.predictions() if r['prediction_id']!=key)
    assert late['history_shadow']['reason']=='invalid_or_late_recording'
    assert late['model_probability']==original['model_probability']


async def test_bounded_loader_uses_readonly_snapshot_and_bound_player_ids():
    p,rows,_=fixture();conn=MagicMock();conn.transaction.return_value.__aenter__=AsyncMock()
    conn.transaction.return_value.__aexit__=AsyncMock();conn.fetch=AsyncMock(return_value=rows)
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock()
    got=await shadow.load_histories(pool,'nfl',2026,date.fromisoformat(p['game_date']),{('00-1','rec_yds')})
    assert got['00-1','rec_yds']==rows
    conn.transaction.assert_called_once_with(isolation='repeatable_read',readonly=True)
    args=conn.fetch.call_args
    assert args.args[1:]==(['00-1'],2024,2026,date.fromisoformat(p['game_date']))
    assert 'rn<=40' in args.args[0] and '00-1' not in args.args[0]
    assert args.kwargs['timeout']==4
    assert await shadow.load_histories(pool,'cfb',2026,date.today(),{('1','rec_yds')})=={}


def audit_rows(monkeypatch, count=2):
    # Isolate grouping/scoring from the separate cryptographic/settlement tests.
    monkeypatch.setattr(audit,'_eligible',lambda *args:True)
    monkeypatch.setattr(audit,'verified_shadow_probability',lambda p:p.get('candidate'))
    monkeypatch.setattr(audit,'verified_recorded_market_baseline',lambda p:p.get('market'))
    monkeypatch.setattr(audit,'_verified_outcome',lambda p:p.get('outcome'))
    p,_,_=fixture()
    return [p|dict(prediction_id=str(i),game_id=f'game{i}',player_id=f'player{i}',
        history_shadow={'model_version':shadow.VERSION},candidate=.65,market=.5,
        model_probability=.55,outcome=True) for i in range(count)]


def test_scoring_deduplicates_before_availability_or_result_selection(monkeypatch):
    rows=audit_rows(monkeypatch)
    early=rows[0]|dict(candidate=None,history_shadow={'model_version':shadow.VERSION,'reason':'low_prior_workload'})
    later=rows[0]|dict(prediction_id='later',captured_at=(datetime.fromisoformat(early['captured_at'])+timedelta(seconds=1)).isoformat())
    opposite=rows[1]|dict(prediction_id='under',direction='under',candidate=.35,outcome=False)
    report=audit.report_history_shadow([later,early,rows[1],opposite],'nfl')
    result=report['markets']['rec_yds']
    assert report['earliest_attempts']==2 and report['duplicate_attempts']==2
    assert result['counts']['unavailable']==1 and result['counts']['paired_decided']==1
    assert result['candidate']['game_balanced_brier']==pytest.approx(.35**2)
    assert result['status']=='insufficient_data' and report['promote'] is False


def test_pending_unpaired_and_cluster_support_never_produce_roi(monkeypatch):
    rows=audit_rows(monkeypatch,50)
    result=audit.report_history_shadow(rows,'nfl')['markets']['rec_yds']
    assert result['status']=='predictive_evidence_supported' and result['promote'] is False
    assert 'roi' not in result
    rows[0]['outcome']=None;rows[1]['market']=None
    result=audit.report_history_shadow(rows,'nfl')['markets']['rec_yds']
    assert result['counts']['pending']==1 and result['counts']['unpaired']==1
    assert result['paired_games']==48 and result['status']=='insufficient_data'
    empty=audit.report_history_shadow([],'nba')['markets']['points']
    assert empty['counts']['attempts']==0 and 'candidate' not in empty


@pytest.mark.parametrize('failed_read',[False,True])
async def test_scan_shadow_has_no_effect_on_primary_forecasts_or_exposure(tmp_path,monkeypatch,failed_read):
    from sportsbet import scan
    from sportsbet.config import settings
    from sportsbet.graph.models import PropResult
    p,rows,event=fixture();now=datetime.fromisoformat(p['captured_at'])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return now
    monkeypatch.setattr(scan,'datetime',Clock)
    conn=MagicMock();conn.fetch=AsyncMock(return_value=[{'normalized_name':'player','player_id':'00-1'}])
    pool=MagicMock();pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__=AsyncMock()
    monkeypatch.setattr(scan,'write_player_prop_snapshots',AsyncMock())
    graph=MagicMock();graph.ainvoke=AsyncMock(return_value={'prop_result':PropResult(
        true_probability=Decimal(str(p['model_probability'])),sample_size=40,
        mean_stat=Decimal(str(p['model_mean_stat'])),
        confidence_interval=(Decimal('.3'),Decimal('.7')))})
    monkeypatch.setattr(scan,'create_graph',lambda **kwargs:graph)
    load=AsyncMock(side_effect=RuntimeError('private database detail')) if failed_read else AsyncMock(
        return_value={('00-1','rec_yds'):rows})
    monkeypatch.setattr(scan,'load_histories',load)
    baseline_ledger=Ledger(tmp_path/'baseline.sqlite');shadow_ledger=Ledger(tmp_path/'candidate.sqlite')
    monkeypatch.setattr(settings,'history_shadow_enabled',False)
    baseline=await scan.evaluate_event(pool,event,'nfl',baseline_ledger,'same')
    load.assert_not_awaited()
    monkeypatch.setattr(settings,'history_shadow_enabled',True)
    candidate=await scan.evaluate_event(pool,event,'nfl',shadow_ledger,'same')
    assert baseline['signals']==candidate['signals']
    assert baseline['coverage']['counts']==candidate['coverage']['counts']
    assert len(shadow_ledger.predictions())==2
    for row in shadow_ledger.predictions():
        if failed_read:
            assert row['history_shadow']['reason']=='history_read_failed'
            assert 'private database detail' not in str(row)
        else:
            assert shadow.verified_shadow_probability(row) is not None
        assert row['accepted'] is False and row['stake_fraction']==0
    assert all('history_shadow' not in item for item in candidate['signals'])
    with shadow_ledger.connect() as db:
        assert db.execute('SELECT count(*) FROM exposure').fetchone()[0]==0


@pytest.mark.parametrize('features',[[],[0],[0]*8,[True]*7,[float('nan')]*7,'invalid'])
def test_malformed_feature_arrays_cannot_break_record_verification(features):
    p,rows,_=fixture();record=shadow.shadow_record(p,rows)
    record['features']=features
    if isinstance(features,list) and any(isinstance(v,float) and math.isnan(v) for v in features):
        # Invalid JSON is rejected by the integrity check itself.
        record['record_sha256']='a'*64
    else:
        record['record_sha256']=shadow.digest({k:v for k,v in record.items() if k!='record_sha256'})
    assert shadow.verified_shadow_probability(p|{'history_shadow':record}) is None


@pytest.mark.parametrize('delay',[301,90000])
def test_identical_late_shadow_retry_keeps_original_receipt(tmp_path,monkeypatch,delay):
    p,rows,_=fixture();p['history_shadow']=shadow.shadow_record(p,rows)
    assert p['history_shadow']['status']=='predicted'
    captured=datetime.fromisoformat(p['captured_at'])
    class Late(datetime):
        @classmethod
        def now(cls,tz=None):return captured+timedelta(seconds=delay)
    monkeypatch.setattr('sportsbet.ledger.datetime',Late)
    ledger=Ledger(tmp_path/'late.sqlite')
    original=deepcopy(p);key=ledger.record('same',p)
    retained=ledger.predictions()[0]
    assert retained['history_shadow']['reason']=='invalid_or_late_recording'
    assert shadow.verified_recorded_shadow_probability(retained) is None
    assert ledger.record('same',p)==key
    assert ledger.predictions()==[retained]
    assert p==original
    for change in ({'model_probability':.1},{'history_shadow':p['history_shadow']|{'probability':.123}}):
        with pytest.raises(ValueError,match='immutable'):
            ledger.record('same',p|change)
    assert ledger.predictions()==[retained]
