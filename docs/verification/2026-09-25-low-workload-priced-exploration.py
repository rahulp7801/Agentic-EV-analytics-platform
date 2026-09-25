"""Exploratory market-relative scoring of the retained low-workload coverage audit.

The candidate and reconstructed features are retrospective, never prospective
predictions. Missing legacy means remain in a separate reporting stratum.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from sportsbet.quant.audit_storage import ReadOnlyLedger, audit_database_url
from sportsbet.quant.history_shadow import predicted_over
from sportsbet.quant.history_tuning import Example, compare, score
from sportsbet.quant.priced_market_audit import _eligible, _verified_outcome, _quote_key, _implied
from sportsbet.quant.market_baseline import verified_recorded_market_baseline


def audit(coverage_path, candidate_path):
    coverage=json.loads(coverage_path.read_text(encoding='utf-8-sig'))
    artifact=json.loads(candidate_path.read_text(encoding='utf-8-sig'))
    if coverage.get('audit_version')!='low-workload-offer-coverage-v2':
        raise ValueError('Unsupported coverage protocol')
    load_dotenv()
    records={str(r['prediction_id']):r for r in ReadOnlyLedger(database_url=audit_database_url()).predictions()}
    quotes=defaultdict(lambda:defaultdict(set))
    for row in records.values():
        if _eligible(row,'nfl','empirical-jeffreys-v4') is not None:
            quotes[_quote_key(row)][row['direction']].add(row['american_odds'])
    seen=set()
    for item in coverage['evidence_details']:
        key=(item['game_id'],item['player_id'],item['prop_type'],float(item['line']))
        if key in seen:raise ValueError('Duplicate coverage threshold')
        seen.add(key)
    results={}
    for prop, model in artifact['sports']['nfl']['props'].items():
        selected=model['selected']
        params=model['fitted_corrections'].get(selected)
        if params is None:
            results[prop]={'status':'no_correction_candidate','promote':False};continue
        strata={}
        for status in ('complete_agreement','partial_agreement_missing_mean'):
            exclusions=Counter();examples=[];candidate=[];market=[]
            for item in coverage['evidence_details']:
                if item['prop_type']!=prop or item['evidence']['status']!=status:continue
                row=records.get(str(item['prediction_id']))
                if row is None or _eligible(row,'nfl','empirical-jeffreys-v4') is None:
                    exclusions['invalid_or_missing_offer']+=1;continue
                if any(row.get(k)!=item.get(k) for k in ('game_id','player_id','prop_type','line','direction','captured_at','model_sample_size','model_probability','model_mean_stat')):
                    raise ValueError('Forecast binding changed')
                if 'paired_over_market_probability' not in item:
                    exclusions['unpaired_market']+=1;continue
                raw=_implied(row['american_odds'])
                other='under' if row['direction']=='over' else 'over'
                opposite=quotes[_quote_key(row)].get(other,set())
                paired=raw/(raw+_implied(next(iter(opposite)))) if len(opposite)==1 else None
                committed=verified_recorded_market_baseline(row)
                if paired is not None and committed is not None and abs(paired-committed)>1e-10:
                    raise ValueError('Conflicting current market evidence')
                no_vig=committed if committed is not None else paired
                if no_vig is None:raise ValueError('Missing current market evidence')
                over_market=no_vig if row['direction']=='over' else 1-no_vig
                if abs(over_market-item['paired_over_market_probability'])>1e-10:
                    raise ValueError('Market binding changed')
                outcome=_verified_outcome(row)
                if type(outcome) is not bool:
                    exclusions['no_authenticated_decided_outcome']+=1;continue
                try:
                    p=predicted_over(item['features'],params)
                except ValueError:
                    exclusions['outside_candidate_feature_range']+=1;continue
                # Outcomes never select rows, candidates or thresholds. They are
                # read only after the earliest coverage cohort has been fixed.
                y=int(outcome) if item['direction']=='over' else 1-int(outcome)
                base=float(row['model_probability'])
                if item['direction']=='under':base=1-base
                examples.append(Example('evaluate',str(row['game_id']),row['player_id'],
                    date.fromisoformat(item['game_date']),float(item['line']),y,base,base,base,
                    tuple(item['features']),item['model_sample_size'],False))
                candidate.append(p);market.append(item['paired_over_market_probability'])
            base=np.asarray([e.base for e in examples]);candidate=np.asarray(candidate);market=np.asarray(market)
            strata[status]={'exclusions':dict(exclusions),'baseline':score(examples,base),
                'candidate':score(examples,candidate),'market':score(examples,market),
                'candidate_minus_market':compare(examples,market,candidate) if examples else None,
                'candidate_minus_baseline':compare(examples,base,candidate) if examples else None}
        results[prop]={'candidate':selected,'strata':strata,'promote':False}
    return {'generated_at':datetime.now(timezone.utc).isoformat(),
        'protocol':'low-workload-priced-exploration-v1','read_only':True,'promote':False,
        'coverage_sha256':hashlib.sha256(coverage_path.read_bytes()).hexdigest(),
        'candidate_sha256':hashlib.sha256(candidate_path.read_bytes()).hexdigest(),'props':results,
        'limitations':['Retrospective reconstructed features and candidate; not frozen prospective predictions.',
            'Evaluation-period outcomes have been examined in previous research; exploratory repeated testing.',
            'Missing mean metadata is partial evidence, reported separately, never backfilled.',
            'Historical workload values are not covered by core-stat commitments; source corrections can postdate forecasts.',
            'Few independent games; intervals are descriptive and do not establish market advantage.',
            'Brier and log loss across quoted thresholds are not a recommendation policy or profit estimate.']}

if __name__=='__main__':
    try:
        result=audit(Path('docs/verification/2026-09-25-low-workload-offers-v2.json'),
                     Path('docs/verification/2026-09-24-low-workload-nfl.json'))
        Path('.local/low-workload-priced-exploration.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        print(json.dumps({p:{s:{'games':v['candidate']['games'],
            'candidate_brier':v['candidate'].get('game_balanced_brier'),
            'market_brier':v['market'].get('game_balanced_brier')} for s,v in r.get('strata',{}).items()} for p,r in result['props'].items()}))
    except Exception as exc:
        raise SystemExit('Priced audit unavailable: '+type(exc).__name__) from None
