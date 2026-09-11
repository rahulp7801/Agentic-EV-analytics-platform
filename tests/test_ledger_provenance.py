import json

import pytest

from sportsbet.ledger import Ledger


def payload(**overrides):
    return dict(game_id='g', player='P', prop_type='points', direction='over', line=20.5,
        sportsbook='book', american_odds=100, model_probability=.6,
        captured_at='2026-01-01T15:00:00+00:00', game_start_time='2026-01-01T20:00:00+00:00',
        model_version='v1') | overrides


def test_naive_timestamps_are_not_silently_assigned_the_host_timezone(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite')
    with pytest.raises(ValueError,match='timezone'):
        ledger.record('s',payload(captured_at='2026-01-01T15:00:00'))
    assert ledger.predictions()==[]
    key=ledger.record('s',payload(captured_at='2026-01-01T10:00:00-05:00'))
    assert ledger.record('s',payload())==key
    with pytest.raises(ValueError,match='immutable'):
        ledger.record('s',payload(american_odds=120))
    assert ledger.predictions()[0]['american_odds']==100


def test_legacy_utc_chronology_and_model_cohorts(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite')
    # Insert legacy offset strings directly: lexical order picks the later 10:00-07 quote.
    with ledger.connect() as db:
        for key,time,prob,version in [('earlier','2026-01-01T15:00:00+00:00',.8,'v1'),
                                      ('later','2026-01-01T10:00:00-07:00',.2,'v2')]:
            db.execute('INSERT INTO predictions VALUES (?,?,?,?)',
                (key,key,json.dumps(payload(captured_at=time,model_probability=prob,model_version=version)),'true'))
        db.execute('INSERT INTO predictions VALUES (?,?,?,?)',
            ('invalid','s',json.dumps(payload(captured_at='2026-01-01T10:00:00')),'true'))
    report=ledger.report()
    assert report['brier_score']==pytest.approx(.04)
    assert report['excluded_missing_metadata']==1 and report['duplicate_predictions']==1
    assert report['available_model_versions']==['v1','v2']
    assert ledger.report(model_version='v2')['brier_score']==pytest.approx(.64)
    assert ledger.report(model_version='missing')['sample_size']==0


@pytest.mark.parametrize('changes',[
    {'quote_time':'2026-01-01T16:00:00+00:00'},
    {'model_generated_at':'2026-01-01T16:00:00+00:00'},
    {'sportsbook':'prizepicks'}, {'model_probability':2}, {'american_odds':1},
])
def test_unusable_evidence_is_excluded_from_metrics(tmp_path,changes):
    ledger=Ledger(tmp_path/'audit.sqlite')
    ledger.record('s',payload(**changes))
    report=ledger.report()
    assert report['sample_size']==0 and report['excluded_missing_metadata']==1
    assert report['roi'] is None and report['brier_score'] is None
