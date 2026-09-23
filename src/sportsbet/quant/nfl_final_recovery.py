"""Preview or atomically apply an explicit, archived NFL final-result recovery."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path

from sportsbet.ingestion.nfl_final_evidence import inspect_bundle,plan_recovery
from sportsbet.ledger import json_object,VERIFIED_SETTLEMENT_SOURCE,verified_settlement_evidence
from sportsbet.quant.audit_storage import ReadOnlyLedger,audit_database_url
from sportsbet.settlement import _actual


def pending_rows(db,evidence):
    players=sorted({e['player_id'] for e in evidence})
    dates=sorted({e['game']['date'] for e in evidence})
    if not players or not dates:return []
    rows=db.execute('''SELECT id,payload FROM predictions WHERE outcome IS NULL
        AND payload::jsonb->>'sport'='nfl' AND payload::jsonb->>'player_id'=ANY(?)
        AND payload::jsonb->>'game_date'=ANY(?)''',(players,dates)).fetchall()
    return [json_object(payload)|dict(prediction_id=key,outcome=None) for key,payload in rows]


def apply_plan(conn,plan):
    """Caller owns one transaction; lock and validate every row before writing."""
    updates=plan['updates'];keys=[u['prediction_id'] for u in updates]
    if not keys:return 0
    if len(set(keys))!=len(keys):raise ValueError('Duplicate recovery prediction')
    retained=conn.execute('SELECT id,payload,outcome FROM analytics.predictions WHERE id=ANY(%s) ORDER BY id FOR UPDATE',(keys,)).fetchall()
    if len(retained)!=len(keys):raise ValueError('Recovery prediction disappeared')
    by_id={key:(json_object(payload),outcome) for key,payload,outcome in retained}
    class Session:
        def execute(self,sql,args=()):return conn.execute(sql.replace('?', '%s'),args)
    db=Session();stats={};values=[]
    for u in updates:
        current,outcome=by_id[u['prediction_id']]
        expected={k:v for k,v in u['payload'].items() if k not in ('prediction_id','outcome')}
        if outcome is not None or current!=expected:
            raise ValueError('Recovery forecast or outcome changed; re-preview required')
        proof=u['evidence'];game={k:proof[k] for k in ('provider_event_id','date','home_abbr','away_abbr','home_name','away_name','completed','game_time')}
        stat_key=(current['player_id'],current['prop_type'],game['provider_event_id'])
        if stat_key not in stats:
            stats[stat_key]=_actual(db,current,'nfl',game['date'],game)
        observed=stats[stat_key]
        if observed is not None and observed[0]!=u['actual']:
            raise ValueError('Final sources disagree; recovery aborted')
        if not verified_settlement_evidence(current,u['outcome'],VERIFIED_SETTLEMENT_SOURCE,
                u['source_ref'],u['observed_at'],u['actual'],proof):
            raise ValueError('Invalid recovery proof')
        values.append((json.dumps(u['outcome']),VERIFIED_SETTLEMENT_SOURCE,u['source_ref'],u['observed_at'],u['actual'],json.dumps(proof,sort_keys=True,separators=(',',':')),u['prediction_id']))
    with conn.cursor() as cursor:
        cursor.executemany('''UPDATE analytics.predictions SET outcome=%s,outcome_source=%s,
            outcome_ref=%s,outcome_observed_at=%s,actual_value=%s,outcome_evidence=%s
            WHERE id=%s AND outcome IS NULL''',values)
        if cursor.rowcount!=len(values):raise ValueError('Recovery write count changed')
    return len(values)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--database-env')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-count',type=int)
    args=parser.parse_args()
    if args.apply and (args.expected_count is None or args.expected_count<=0):
        parser.error('--apply requires a positive reviewed --expected-count')
    try:
        raw=args.bundle.read_bytes()
        bundle=json.loads(gzip.decompress(raw) if args.bundle.suffix=='.gz' else raw)
        evidence=inspect_bundle(bundle)
        url=audit_database_url(args.database_env);ledger=ReadOnlyLedger(database_url=url)
        with ledger.snapshot(),ledger.connect() as db:
            plan=plan_recovery(pending_rows(db,evidence),evidence)
        count=len(plan['updates'])
        if args.expected_count is not None and args.expected_count!=count:
            raise ValueError('Recovery count differs from reviewed preview')
        applied=0
        if args.apply:
            import psycopg
            with psycopg.connect(url.replace('postgresql+psycopg://','postgresql://',1),connect_timeout=15,
                    options='-c statement_timeout=60000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=60000') as conn:
                conn.execute('SET LOCAL search_path TO analytics, public')
                conn.execute("SET LOCAL application_name='sportsbet_explicit_final_recovery'")
                applied=apply_plan(conn,plan)
        result=dict(observed_at=datetime.now(timezone.utc).isoformat(),mode='applied' if args.apply else 'read_only_preview',
            bundle_sha256=hashlib.sha256(raw).hexdigest(),players=dict(Counter(e['status'] for e in evidence)),
            proposed_results=count,applied_results=applied,did_not_play_pending=len(plan['did_not_play_pending']),
            outcomes=dict(Counter(str(u['outcome']) for u in plan['updates'])),
            accepted_forecasts=sum(u['payload'].get('accepted') is True for u in plan['updates']),
            source_player_results=[dict(player_id=e['player_id'],espn_player_id=e['espn_player_id'],
                event=e['game']['provider_event_id'],status=e['status'],stats=e.get('stat_row')) for e in evidence])
        print(json.dumps(result,indent=2,sort_keys=True))
    except Exception as exc:
        raise SystemExit(f'Explicit final recovery unavailable: {type(exc).__name__}') from None


if __name__=='__main__':main()
