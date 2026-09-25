"""Read-only exploratory offered-market coverage; never fits or scores outcomes."""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

from sportsbet.quant.history_tuning import PROPS, QUERIES
from sportsbet.quant.history_features import history_estimates
from sportsbet.quant.priced_market_audit import _eligible, _quote_key, _implied
from sportsbet.quant.market_baseline import verified_recorded_market_baseline
from sportsbet.ingestion.provenance import stat_row_sha256


def audit():
    load_dotenv()
    with psycopg.connect(os.environ['DATABASE_URL'].replace('postgresql+psycopg://','postgresql://'),
            row_factory=dict_row, connect_timeout=15,
            options='-c default_transaction_read_only=on -c statement_timeout=120000') as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        # Intentionally never load any outcome or settlement column.
        forecasts=db.execute("SELECT id,payload FROM analytics.predictions ORDER BY id").fetchall()
        histories=db.execute(QUERIES['nfl'].replace('BETWEEN 2023 AND 2025','BETWEEN 2023 AND 2026')).fetchall()
    rows=[]
    for record in forecasts:
        payload=record['payload']
        row=(json.loads(payload) if isinstance(payload,str) else payload) | {'prediction_id':record['id']}
        if _eligible(row,'nfl','empirical-jeffreys-v4') is not None:
            rows.append(row)
    rows.sort(key=lambda r:(r['captured_at'],str(r['prediction_id'])))
    quotes=defaultdict(lambda:defaultdict(set))
    for row in rows: quotes[_quote_key(row)][row['direction']].add(row['american_odds'])
    grouped=defaultdict(list)
    for row in histories:
        if row['day'] is not None and row['game']:
            grouped[str(row['player'])].append(row)
    for values in grouped.values(): values.sort(key=lambda r:(r['day'],r['game']))
    counts={p:Counter() for p in PROPS['nfl']}
    covered={p:[] for p in PROPS['nfl']}
    seen=set()
    for row in rows:
        prop=row['prop_type']
        if prop not in counts: continue
        key=(row['game_id'],row.get('player_id'),prop,str(row['line']))
        if key in seen: continue
        seen.add(key) # Earliest threshold fixed before scope checks; no later rescue.
        c=counts[prop]; c['earliest_offered_thresholds']+=1
        line=float(row['line'])
        if not math.isfinite(line) or line<.5 or not (line*2).is_integer() or line.is_integer():
            c['unsupported_line']+=1;continue
        day=date.fromisoformat(row['game_date']);season=day.year if day.month>=9 else day.year-1
        stat,work,min_work=PROPS['nfl'][prop]
        prior=[r for r in grouped[row.get('player_id')] if r['day']<day and season-2<=r['season']<=season and r[stat] is not None][-40:]
        if not 20<=len(prior)<=40: c['insufficient_history']+=1;continue
        if len({r['game'] for r in prior})!=len(prior): c['ambiguous_history']+=1;continue
        if any(stat_row_sha256('nfl',r)!=r['source_record_sha256'] for r in prior):
            c['invalid_core_stat_commitment']+=1;continue
        if any(r[work] is None or isinstance(r[work],bool) or not math.isfinite(float(r[work])) or r[work]<0 for r in prior):
            c['invalid_workload']+=1;continue
        if not any(r[work]>0 for r in prior): c['no_prior_category_workload']+=1;continue
        if statistics.fmean(r[work] for r in prior[-5:])>=min_work:
            c['eligible_original_workload_scope']+=1;continue
        c['low_workload']+=1
        estimate=history_estimates(prior,stat,work,day,line)
        expected=estimate['base'] if row['direction']=='over' else 1-estimate['base']
        if (row.get('model_sample_size')!=estimate['sample'] or abs(float(row['model_probability'])-expected)>1e-6
                or abs(float(row.get('model_mean_stat',-999))-estimate['mean'])>.005001 or float(row.get('push_probability',-1))!=0):
            c['baseline_reconstruction_mismatch']+=1;continue
        c['baseline_agreement']+=1
        other='under' if row['direction']=='over' else 'over'
        opposite=quotes[_quote_key(row)].get(other,set())
        raw=_implied(row['american_odds'])
        paired=raw/(raw+_implied(next(iter(opposite)))) if len(opposite)==1 else None
        committed=verified_recorded_market_baseline(row)
        if paired is not None and committed is not None and abs(paired-committed)>1e-10:
            c['conflicting_market_pair']+=1;continue
        if committed is None and paired is None: c['missing_market_pair']+=1;continue
        c['paired_low_workload']+=1
        covered[prop].append(key)
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'read_only':True,
        'outcomes_loaded':False,'model_version':'empirical-jeffreys-v4','promote':False,
        'eligible_forecasts':len(rows),'history_rows':len(histories),
        'history_sha256':hashlib.sha256(json.dumps(histories,sort_keys=True,default=str).encode()).hexdigest(),
        'forecast_sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest(),
        'props':{p:{'counts':dict(counts[p]),'paired_games':len({k[0] for k in covered[p]}),
                   'paired_players':len({k[1] for k in covered[p]})} for p in counts},
        'limitations':['Retrospective reconstruction from current database; source corrections may postdate forecast.',
            'Core stat hash does not authenticate workload fields.',
            'Earliest game/player/market/line before coverage; complementary sides and sportsbooks deduplicated.',
            'No outcome selection, candidate scoring, market-edge or prospective-evidence claim.']}

if __name__=='__main__':
    try:
        print(json.dumps(audit(),indent=2,allow_nan=False))
    except Exception as exc:
        raise SystemExit('Coverage audit unavailable: '+type(exc).__name__) from None
