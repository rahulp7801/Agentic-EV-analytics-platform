import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec=importlib.util.spec_from_file_location('low_workload_priced',Path(__file__).resolve().parents[1]/'docs/verification/2026-09-25-low-workload-priced-exploration.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def setup_audit(tmp_path,monkeypatch):
    rows=[];details=[]
    for index,status in enumerate(('complete_agreement','partial_agreement_missing_mean')):
        r=dict(prediction_id=str(index),player_id='player',game_id='g'+str(index),prop_type='rush_yds',
            line=2.5,direction='under',captured_at='2026-09-19T00:00:00+00:00',
            model_sample_size=30,model_probability=.75,model_mean_stat=1 if index==0 else None,
            american_odds=-110,outcome=True)
        rows.append(r)
        details.append({k:v for k,v in r.items() if k not in ('american_odds','outcome')} |
            {'evidence':{'status':status},'features':[0]*7,'game_date':'2026-09-20',
             'paired_over_market_probability':.5})
    coverage=tmp_path/'coverage.json';candidate=tmp_path/'candidate.json'
    coverage.write_text(json.dumps({'audit_version':'low-workload-offer-coverage-v2','evidence_details':details}))
    candidate.write_text(json.dumps({'sports':{'nfl':{'props':{'rush_yds':{'selected':'fixed','fitted_corrections':{'fixed':{}}}}}}}))
    monkeypatch.setattr(audit,'load_dotenv',lambda:None)
    monkeypatch.setattr(audit,'audit_database_url',lambda:'unused')
    monkeypatch.setattr(audit,'ReadOnlyLedger',lambda **_:SimpleNamespace(predictions=lambda:rows))
    monkeypatch.setattr(audit,'_eligible',lambda *a,**k:True)
    monkeypatch.setattr(audit,'verified_recorded_market_baseline',lambda r:.5)
    monkeypatch.setattr(audit,'_verified_outcome',lambda r:r['outcome'])
    monkeypatch.setattr(audit,'predicted_over',lambda features,params:.2)
    return rows,details,coverage,candidate


def test_partial_stratum_stays_separate_under_outcomes_are_inverted(setup_audit):
    rows,details,coverage,candidate=setup_audit
    r=audit.audit(coverage,candidate)
    assert r['promote'] is False
    strata=r['props']['rush_yds']['strata']
    for s in strata.values():
        assert s['candidate']['examples']==1
        assert s['candidate']['game_balanced_brier']==pytest.approx(.04)
        assert s['baseline']['game_balanced_brier']==pytest.approx(.0625)
    rows[1]['outcome']=None
    r=audit.audit(coverage,candidate)['props']['rush_yds']['strata']
    assert r['partial_agreement_missing_mean']['candidate']['examples']==0
    assert r['complete_agreement']['candidate']['examples']==1


def test_changed_forecast_or_market_cannot_be_scored(setup_audit):
    rows,details,coverage,candidate=setup_audit
    rows[0]['model_probability']=.9
    with pytest.raises(ValueError,match='Forecast binding'):audit.audit(coverage,candidate)
    rows[0]['model_probability']=.75
    details[0]['paired_over_market_probability']=.8
    coverage.write_text(json.dumps({'audit_version':'low-workload-offer-coverage-v2','evidence_details':details}))
    with pytest.raises(ValueError,match='Market binding'):audit.audit(coverage,candidate)


def test_duplicate_thresholds_fail_before_scoring(setup_audit):
    rows,details,coverage,candidate=setup_audit
    details.append(details[0])
    coverage.write_text(json.dumps({'audit_version':'low-workload-offer-coverage-v2','evidence_details':details}))
    with pytest.raises(ValueError,match='Duplicate coverage'):audit.audit(coverage,candidate)
