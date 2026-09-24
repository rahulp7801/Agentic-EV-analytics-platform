import copy
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

import pytest

from sportsbet.quant.nfl_history_sensitivity import estimate,read_archive,sensitivity

ROOT=Path(__file__).resolve().parents[1]/'docs'/'verification'
NOW=datetime(2026,9,25,tzinfo=timezone.utc)

@pytest.fixture(scope='module')
def retained():
    history=read_archive(ROOT/'2026-09-23-nfl-history-coverage-input.json.gz')
    recovery=read_archive(ROOT/'2026-09-24-nfl-missing-history-sources.json.gz')
    identity=read_archive(ROOT/'2026-09-23-nfl-final-sources.json.gz')['identity']
    for data in (history,recovery):
        assert data['identity_source_sha256']==identity['source_sha256']
        data['identity']=identity
    return history,recovery,read_archive(ROOT/'2026-09-24-nfl-history-sensitivity-quotes.json')


def test_retained_sources_reproduce_material_sensitivity_without_mutating_inputs(retained):
    original=copy.deepcopy(retained)
    report=sensitivity(*retained,now=NOW)
    assert retained==original
    assert report['verified_missing_games']==12
    assert report['players_with_recovery']==4
    assert report['receiving_offer_comparisons']==60
    assert all(r['receptions']==r['receiving_yards']==0 for r in report['recovered_games'])
    row,=[r for r in report['comparisons'] if r['player']=='Austin Hooper' and r['direction']=='over']
    assert row['line']==0.5
    assert row['baseline']['sample_size']==31
    assert row['augmented_history']['sample_size']==35
    assert row['baseline']['probability']==0.953125
    assert row['augmented_history']['probability']==0.847222
    assert row['probability_change_pp']==-10.5903
    hooper=next(p for p in report['history_composition'] if p['player']=='Austin Hooper')
    assert sum(c['games'] for c in hooper['cohorts'] if c['team']=='NE')==33
    assert next(c for c in hooper['cohorts'] if c['team']=='ATL')['games']==2
    assert report['mode']=='retrospective_sensitivity_only'
    assert report['production_writes']==report['published_forecasts']==report['provider_quote_requests']==0


@pytest.mark.parametrize('fault',['quote_hash','late_capture','cutoff','identity','outside_scope','duplicate_evidence','duplicate_offer','future_market','invalid_line','invalid_odds'])
def test_cross_archive_or_market_mismatch_fails_closed(retained,fault):
    history,recovery,offers=copy.deepcopy(retained)
    if fault=='quote_hash':offers['payload_sha256']='0'*64
    elif fault=='late_capture':offers['captured_at']=offers['event']['commence_time']
    elif fault=='cutoff':history['cutoff']='2026-09-23'
    elif fault=='identity':recovery['identity']['source_sha256']='0'*64
    elif fault=='outside_scope':
        for player in history['players']:player['current_quoted']=False
    elif fault=='duplicate_evidence':recovery['players'].append(recovery['players'][0])
    else:
        import hashlib,json
        market=next(m for b in offers['event']['bookmakers'] for m in b['markets'] if m['key']=='player_receptions')
        offer=next(o for o in market['outcomes'] if o['description']=='Christian Watson')
        if fault=='duplicate_offer':market['outcomes'].append(offer)
        elif fault=='future_market':market['last_update']='2026-09-24T10:00:00Z'
        elif fault=='invalid_line':offer['point']=float('nan')
        elif fault=='invalid_odds':offer['price']=0
        offers['payload_sha256']=hashlib.sha256(json.dumps(offers['event'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    with pytest.raises((ValueError,KeyError)):
        sensitivity(history,recovery,offers,now=NOW)


def test_window_applies_cutoff_and_null_filter_before_last40_and_keeps_pushes():
    rows=[dict(season=2024+i//18,week=i%18+1,date='2025-01-01',receptions=1) for i in range(40)]
    rows += [dict(season=2026,week=1,date='2026-09-13',receptions=0,explicit_recovery=True),
             dict(season=2026,week=2,date='2026-09-20',receptions=None),
             dict(season=2026,week=3,date='2026-09-24',receptions=99)]
    over=estimate(rows,'receptions',Decimal('0.5'),'over','2026-09-24',2024)
    under=estimate(rows,'receptions',Decimal('0.5'),'under','2026-09-24',2024)
    assert over['sample_size']==40 and over['successes_over']==39 and over['added_games_in_window']==1
    assert over['probability']+under['probability']==1
    push=estimate(rows,'receptions',Decimal('1'),'under','2026-09-24',2024)
    assert push['pushes']==39 and push['push_probability']==0.975
    assert push['probability']==0.01875


def test_empty_and_all_push_cohorts_remain_unavailable():
    assert estimate([],'receptions',Decimal('0.5'),'over','2026-09-24',2024)['probability'] is None
    row=dict(season=2026,week=1,date='2026-09-13',receptions=1)
    assert estimate([row],'receptions',Decimal('1'),'under','2026-09-24',2024)['probability'] is None
