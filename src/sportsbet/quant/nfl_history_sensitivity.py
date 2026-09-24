"""Offline sensitivity to explicitly verified missing NFL receiving history.

This retrospectively augmented dataset is not a new model, backtest, or live pick.
The CLI reads retained files only; it never writes the database or fetches quotes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsbet.ingestion.nfl_final_evidence import inspect_bundle
from sportsbet.prop.probability import empirical_outcome_probabilities, outcome_interval_for_side
from sportsbet.quant.nfl_history_coverage import audit, _timestamp

VERSION='nfl-explicit-history-sensitivity-v1'
COLUMNS={'player_receptions':('receptions','receptions'),
         'player_reception_yds':('rec_yds','receiving_yards')}


def estimate(rows:list[dict],column:str,line:Decimal,direction:str,cutoff:str,floor:int) -> dict:
    if direction not in ('over','under') or not line.is_finite() or line<0:
        raise ValueError('Invalid research selection')
    eligible=[r for r in rows if r['season']>=floor and r['date']<cutoff and r.get(column) is not None]
    eligible=sorted(eligible,key=lambda r:(r['season'],r['week']),reverse=True)[:40]
    values=[Decimal(str(r[column])) for r in eligible]
    if any(not v.is_finite() for v in values):raise ValueError('Invalid history value')
    n=len(values);wins=sum(v>line for v in values);pushes=sum(v==line for v in values)
    result=dict(sample_size=n,successes_over=wins,pushes=pushes,
        added_games_in_window=sum(r.get('explicit_recovery',False) for r in eligible),
        probability=None,push_probability=None,confidence_interval=None,
        mean=float(sum(values)/n) if n else None,meets_sample_floor=n>=20)
    if n==0 or pushes==n:return result
    over,push,interval=empirical_outcome_probabilities(wins,pushes,n)
    # Match the existing executor's rounding before converting the selected side.
    over=round(over,6);push=round(push,6);interval=tuple(round(v,6) for v in interval)
    side_interval=outcome_interval_for_side(interval,push,direction)
    result.update(probability=float(over if direction=='over' else 1-push-over),
        push_probability=float(push),confidence_interval=[float(v) for v in side_interval] if side_interval else None)
    return result


def sensitivity(history:dict,recovery:dict,offers:dict,*,now:datetime|None=None) -> dict:
    now=now or datetime.now(timezone.utc)
    coverage=audit(history,now=now)
    if history['identity']['source_sha256']!=recovery['identity']['source_sha256']:
        raise ValueError('Identity archives differ')
    evidence=inspect_bundle(recovery,now=now)
    missing={(r['player_id'],r['season'],r['week']):r for r in coverage['missing_games']}
    scope={r['player_id']:r for r in history['players'] if r['current_quoted']}
    baseline={gsis:[] for gsis in scope};added={gsis:[] for gsis in scope};recovered=[]
    for item in history['stats']:
        row=item['stat']
        if row['player_id'] in baseline:baseline[row['player_id']].append(dict(row,date=item['game_date']))
    for item in evidence:
        if item['status']!='verified_explicit_stats':raise ValueError('Every recovery must have explicit final stats')
        row=item['stat_row'];key=(item['player_id'],row['season'],row['week'])
        gap=missing.get(key);snap=item['source_evidence']['participation']
        if (gap is None or item['player_id'] not in scope or row['team']!=gap['team']
                or item['game']['date']!=gap['day'] or snap['row']['game_id']!=gap['game_id']):
            raise ValueError('Recovery is not an exact missing game in the selected scope')
        original,=[s for s in history['snaps'] if s['game_id']==gap['game_id']
                   and s['snap']['pfr_player_id']==snap['row']['pfr_player_id']]
        if original['snap']['source_record_sha256']!=snap['source_record_sha256']:
            raise ValueError('Participation archives differ')
        added[item['player_id']].append(dict(row,date=gap['day'],explicit_recovery=True))
        recovered.append(dict(player=scope[item['player_id']]['player'],player_id=item['player_id'],
            game_id=gap['game_id'],date=gap['day'],receptions=row['receptions'],receiving_yards=row['receiving_yards'],
            source_sha256=item['source_sha256'],espn_event_id=item['game']['provider_event_id']))
    event=offers['event'];captured=_timestamp(offers['captured_at']);start=_timestamp(event['commence_time'])
    event_hash=hashlib.sha256(json.dumps(event,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if (event_hash!=offers['payload_sha256'] or captured>now or captured>=start
            or start.astimezone(ZoneInfo('America/New_York')).date().isoformat()!=history['cutoff']
            or event.get('sport_key')!='americanfootball_nfl'):
        raise ValueError('Invalid retained NFL quote or cutoff commitment')
    names={}
    for gsis,p in scope.items():
        if p['player'] in names:raise ValueError('Ambiguous quoted player name')
        names[p['player']]=gsis
    comparisons=[];seen=set()
    for book in event['bookmakers']:
        for market in book['markets']:
            if market['key'] not in COLUMNS:continue
            if not _timestamp(market['last_update'])<=captured<start:raise ValueError('Invalid quote chronology')
            prop,column=COLUMNS[market['key']]
            for offer in market['outcomes']:
                gsis=names.get(offer['description'])
                if gsis is None or not added[gsis]:continue
                if (type(offer['point']) not in (int,float) or type(offer['price']) is not int
                        or abs(offer['price'])<100 or offer['name'] not in ('Over','Under')):
                    raise ValueError('Invalid exact market terms')
                line=Decimal(str(offer['point']));direction=offer['name'].lower()
                key=(book['key'],gsis,prop,str(line),direction)
                if key in seen:raise ValueError('Duplicate retained market')
                seen.add(key)
                before=estimate(baseline[gsis],column,line,direction,history['cutoff'],history['season_floor'])
                after=estimate(baseline[gsis]+added[gsis],column,line,direction,history['cutoff'],history['season_floor'])
                comparisons.append(dict(player=scope[gsis]['player'],player_id=gsis,prop_type=prop,line=float(line),
                    direction=direction,sportsbook=book['key'],american_odds=offer['price'],
                    quote_time=market['last_update'],baseline=before,augmented_history=after,
                    probability_change_pp=None if before['probability'] is None or after['probability'] is None
                        else round(100*(after['probability']-before['probability']),6)))
    if not comparisons:raise ValueError('No matching receiving offers')
    composition=[]
    for gsis in sorted(added):
        if not added[gsis]:continue
        cohorts={}
        for row in baseline[gsis]+added[gsis]:
            if row['season']<history['season_floor'] or row['date']>=history['cutoff'] or row['receptions'] is None:continue
            cohorts.setdefault((row['season'],row['team']),[]).append(row['receptions'])
        composition.append(dict(player=scope[gsis]['player'],player_id=gsis,
            scope='All verified prior games in the audit scope, including explicit recovery; descriptive only.',
            cohorts=[dict(season=season,team=team,games=len(values),mean_receptions=sum(values)/len(values),
                zero_reception_games=sum(value==0 for value in values)) for (season,team),values in sorted(cohorts.items())]))
    return dict(version=VERSION,mode='retrospective_sensitivity_only',cutoff=history['cutoff'],season_floor=history['season_floor'],
        quote_captured_at=captured.isoformat(),quote_payload_sha256=event_hash,
        source_evidence_observed_at=max(e['observed_at'] for e in evidence),
        interpretation='Source evidence recovered after capture. These comparisons are not prospective forecasts, qualified picks, or proof of an edge.',
        verified_missing_games=len(recovered),players_with_recovery=sum(bool(v) for v in added.values()),
        receiving_offer_comparisons=len(comparisons),recovered_games=recovered,comparisons=comparisons,
        history_composition=composition,
        production_writes=0,published_forecasts=0,provider_quote_requests=0)


def read_archive(path:Path) -> dict:
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('history','recovery','identity-bundle','quotes'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    try:
        history=read_archive(args.history);recovery=read_archive(args.recovery);identity=read_archive(args.identity_bundle)['identity']
        for data in (history,recovery):
            if data['identity_source_sha256']!=identity['source_sha256']:raise ValueError('Identity archive mismatch')
            data['identity']=identity
        result=sensitivity(history,recovery,read_archive(args.quotes))
        result['input_sha256']={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in vars(args).items()}
        print(json.dumps(result,indent=2,sort_keys=True))
    except Exception as exc:
        raise SystemExit(f'History sensitivity unavailable: {type(exc).__name__}') from None


if __name__=='__main__':main()
