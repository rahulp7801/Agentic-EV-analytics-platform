import json
from datetime import datetime
from decimal import Decimal

import pytest

from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, prop_quote_record_sha256
from sportsbet.ledger import Ledger
from sportsbet.model_contract import MODEL_VERSION
from sportsbet.quant.vig import american_to_raw_prob


def payload(**overrides):
    return dict(game_id='g', player='P', sport='nba', prop_type='points', direction='over', line=20.5,
        sportsbook='book', american_odds=100, model_probability=.6,
        captured_at='2026-01-01T15:00:00+00:00', game_start_time='2026-01-01T20:00:00+00:00',
        model_version='v1') | overrides


def verified_payload(model_version=MODEL_VERSION):
    value=payload(model_version=model_version,
        model_generated_at='2026-01-01T15:00:00+00:00',
        quote_time='2026-01-01T15:00:00+00:00',
        quote_source_provider='the_odds_api',quote_source_sha256='a'*64)
    snapshot=PlayerPropSnapshotCreate(sport='nba',game_id=value['game_id'],
        player_name=value['player'],sportsbook=value['sportsbook'],prop_type='player_points',
        line=Decimal(str(value['line'])),price=value['american_odds'],
        implied_probability=american_to_raw_prob(value['american_odds']),
        game_start_time=datetime.fromisoformat(value['game_start_time']),
        source_provider='the_odds_api',source_sha256=value['quote_source_sha256'],
        snapped_at=datetime.fromisoformat(value['quote_time']),side='Over')
    return value | {'quote_source_record_sha256':prop_quote_record_sha256(snapshot)}


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
            db.execute('INSERT INTO predictions(id,scan_id,payload,outcome) VALUES (?,?,?,?)',
                (key,key,json.dumps(payload(captured_at=time,model_probability=prob,model_version=version)),'true'))
        db.execute('INSERT INTO predictions(id,scan_id,payload,outcome) VALUES (?,?,?,?)',
            ('invalid','s',json.dumps(payload(captured_at='2026-01-01T10:00:00')),'true'))
    report=ledger.report()
    assert report['brier_score'] is None and report['pending_count']==1
    assert report['excluded_missing_metadata']==1 and report['duplicate_predictions']==1
    assert report['unverified_settlements']==3
    assert report['available_model_versions']==['v1','v2']
    selected=ledger.report(model_version='v2')
    assert selected['brier_score'] is None and selected['unverified_settlements']==1
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


def test_invalid_legacy_closing_quote_cannot_crash_or_fabricate_clv(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite')
    ledger.record('s',payload())
    with ledger.connect() as db:
        db.execute('INSERT INTO quotes VALUES (?,?,?)',
            (ledger.quote_identity(payload()),'2026-01-01T16:00:00',.6))
    report=ledger.report()
    assert report['sample_size']==1 and report['pending_count']==1
    assert report['clv_mean'] is None and report['excluded_closing_quotes']==1


def test_provenance_model_versions_keep_requiring_quote_source_commitments(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite')
    current=verified_payload()
    key=ledger.record('valid',current)
    assert ledger.predictions()[0]['prediction_id']==key
    historical=verified_payload('empirical-jeffreys-v3')
    ledger.record('valid-historical',historical)
    with ledger.connect() as db:
        db.execute('INSERT INTO predictions(id,scan_id,payload) VALUES (?,?,?)',
            ('legacy-current','legacy',json.dumps(payload(model_version=MODEL_VERSION))))
        db.execute('INSERT INTO predictions(id,scan_id,payload) VALUES (?,?,?)',
            ('legacy-v3','legacy',json.dumps(payload(model_version='empirical-jeffreys-v3'))))
        db.execute('INSERT INTO predictions(id,scan_id,payload) VALUES (?,?,?)',
            ('tampered-v3','legacy',json.dumps(historical | {'american_odds':110})))
    report=ledger.report(model_version=MODEL_VERSION)
    assert report['sample_size']==1 and report['excluded_missing_metadata']==1
    historical_report=ledger.report(model_version='empirical-jeffreys-v3')
    assert historical_report['sample_size']==1
    assert historical_report['excluded_missing_metadata']==2
    for missing in ('model_generated_at','quote_source_provider','quote_source_sha256','quote_source_record_sha256'):
        invalid=current | {missing:None}
        with pytest.raises(ValueError,match='verified quote evidence'):
            ledger.record('missing-'+missing,invalid)
    with pytest.raises(ValueError,match='verified quote evidence'):
        ledger.record('missing-historical',payload(model_version='empirical-jeffreys-v3'))
    with pytest.raises(ValueError,match='verified quote evidence'):
        ledger.record('tampered-historical',historical | {'line':21.5})
