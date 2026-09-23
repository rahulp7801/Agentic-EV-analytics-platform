"""Read-only prospective scoring of frozen workload shadows; no candidate bets."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path

import numpy as np

from sportsbet.ledger import Ledger,utc_timestamp
from sportsbet.quant.history_shadow import (ARTIFACT_SHA256,FROZEN_AT,MARKETS,POLICY,VERSION,
    implementation_sha256,verified_recorded_shadow_probability as verified_shadow_probability)
from sportsbet.quant.history_tuning import Example,compare,score
from sportsbet.quant.market_baseline import verified_recorded_market_baseline
from sportsbet.quant.priced_market_audit import _eligible,_verified_outcome


def report_history_shadow(rows: list[dict], sport: str) -> dict:
    if sport not in ('nba','nfl','cfb'):
        raise ValueError('Invalid shadow sport')
    report=dict(model_version=VERSION,policy_version=POLICY,artifact_sha256=ARTIFACT_SHA256,
        implementation_sha256=implementation_sha256(),frozen_at=FROZEN_AT,sport=sport,
        generated_at=datetime.now(timezone.utc).isoformat(),status='collecting',promote=False,
        scope='Untraded prospective probability comparison; no candidate acceptance policy or ROI.',
        minimum_paired_games=50,markets={},excluded=0)
    attempts=[]
    for row in rows:
        shadow=row.get('history_shadow')
        if row.get('sport')!=sport or not isinstance(shadow,dict) or shadow.get('model_version')!=VERSION:
            continue
        if (_eligible(row,sport,'empirical-jeffreys-v4') is None
                or utc_timestamp(row['captured_at'])<utc_timestamp(FROZEN_AT)):
            report['excluded']+=1
            continue
        attempts.append(row)
    attempts.sort(key=lambda row:(utc_timestamp(row['captured_at']),row['direction']!='over',row['prediction_id']))
    selected={}
    for row in attempts:
        key=(row['game_id'],row['player_id'],row['prop_type'],float(row['line']))
        selected.setdefault(key,row)  # Choose before status, price-pair or outcome filtering.
    report.update(recorded_attempts=len(attempts),earliest_attempts=len(selected),
        duplicate_attempts=len(attempts)-len(selected))
    for prop in sorted(set(MARKETS.get(sport,{}))|{row['prop_type'] for row in selected.values()}):
        cohort=[row for row in selected.values() if row['prop_type']==prop]
        counts=Counter(attempts=len(cohort));reasons=Counter();examples=[];shadow_p=[];market_p=[]
        for row in cohort:
            probability=verified_shadow_probability(row)
            if probability is None:
                counts['unavailable']+=1
                # Only bounded internal reason codes are retained, never arbitrary messages.
                reason=row['history_shadow'].get('reason','invalid_shadow_record')
                if not isinstance(reason,str) or not reason.replace('_','').isalnum() or len(reason)>60:
                    reason='invalid_shadow_record'
                reasons[reason]+=1
                continue
            counts['valid_predictions']+=1
            market=verified_recorded_market_baseline(row)
            if market is None:
                counts['unpaired']+=1
            else:
                counts['paired_predictions']+=1
            outcome=_verified_outcome(row)
            if type(outcome) is not bool:
                counts['pending']+=1
                continue
            counts['verified_decided']+=1
            if market is None:
                continue
            counts['paired_decided']+=1
            examples.append(Example('evaluate',row['game_id'],row['player_id'],
                date.fromisoformat(row['game_date']),float(row['line']),int(outcome),
                float(row['model_probability']),market,probability,(),row['model_sample_size'],False))
            shadow_p.append(probability);market_p.append(market)
        result=dict(status='insufficient_data',counts={key:counts[key] for key in (
            'attempts','unavailable','valid_predictions','unpaired','paired_predictions','pending',
            'verified_decided','paired_decided')},unavailable_reasons=dict(reasons),promote=False,
            paired_games=len({e.game for e in examples}),paired_players=len({e.player for e in examples}))
        if examples:
            baseline=np.asarray([e.base for e in examples]);candidate=np.asarray(shadow_p);market=np.asarray(market_p)
            result.update(production=score(examples,baseline),candidate=score(examples,candidate),
                market=score(examples,market),candidate_minus_production=compare(examples,baseline,candidate),
                candidate_minus_market=compare(examples,market,candidate))
            if result['paired_games']>=50:
                supported=all(result[comparison][metric+'_'+cluster+'_95'] is not None
                    and result[comparison][metric+'_'+cluster+'_95'][1]<0
                    for comparison in ('candidate_minus_production','candidate_minus_market')
                    for metric in ('brier','log_loss') for cluster in ('game','player'))
                result['status']='predictive_evidence_supported' if supported else 'evidence_not_demonstrated'
        report['markets'][prop]=result
    if sport not in MARKETS:
        report['status']='no_frozen_candidate'
    return report


def publish_history_shadow(rows: list[dict], sport: str, publish) -> None:
    """Research diagnostics cannot change the primary pipeline's success state."""
    import structlog
    try:
        result=report_history_shadow(rows,sport)
    except Exception as exc:
        result=dict(status='unavailable',error_type=type(exc).__name__,promote=False)
    try:
        publish(f'shadow-validation:{sport}',result)
    except Exception as exc:
        structlog.get_logger().warning('shadow_report_unavailable',sport=sport,error_type=type(exc).__name__)


class ReadOnlyLedger(Ledger):
    @contextmanager
    def connect(self):
        import psycopg
        with psycopg.connect(self.database_url.replace('postgresql+psycopg://','postgresql://',1),
                connect_timeout=15,options='-c default_transaction_read_only=on -c statement_timeout=120000') as conn:
            conn.execute('SET LOCAL search_path TO analytics, public')
            yield conn


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport',choices=['nba','nfl','cfb','all'],default='all')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    try:
        rows=ReadOnlyLedger(database_url=os.environ.get('ANALYTICS_DATABASE_URL') or os.environ['DATABASE_URL']).predictions()
        sports=['nba','nfl','cfb'] if args.sport=='all' else [args.sport]
        result={sport:report_history_shadow(rows,sport) for sport in sports}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps({sport:{'attempts':r['earliest_attempts'],'status':r['status']} for sport,r in result.items()}))
    except Exception as exc:
        print(f'Shadow audit unavailable: {type(exc).__name__}')
        raise SystemExit(1) from None


if __name__=='__main__':
    main()
