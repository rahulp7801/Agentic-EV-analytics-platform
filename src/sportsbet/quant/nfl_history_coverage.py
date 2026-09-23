"""Read-only audit of NFL history missing among verified offensive participants.

Missing rows stay unknown. This diagnostic does not create stats, probabilities,
qualified picks, or a new model version.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date,datetime,timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

from sportsbet.ingestion.provenance import row_sha256,stat_row_sha256

SNAP_FIELDS=('game_id','season','week','player_name','pfr_player_id','position','team','opponent','offense_snaps','defense_snaps')
IDENTITY_URL='https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'


def _timestamp(value):
    stamp=datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('Source observation needs a timezone')
    return stamp.astimezone(timezone.utc)


def audit(data: dict, *, now: datetime | None = None) -> dict:
    now=now or datetime.now(timezone.utc)
    observed=_timestamp(data['observed_at']);cutoff=date.fromisoformat(data['cutoff'])
    floor=data['season_floor']
    if observed>now or type(floor) is not int or not 2000<=floor<=cutoff.year:
        raise ValueError('Invalid audit scope')
    identity=data['identity']
    if (identity['url']!=IDENTITY_URL or _timestamp(identity['retrieved_at'])>observed
            or hashlib.sha256(identity['response_text'].encode()).hexdigest()!=identity['source_sha256']):
        raise ValueError('Invalid identity source')
    by_gsis={};pfr_counts=Counter()
    for row in csv.DictReader(io.StringIO(identity['response_text'])):
        gsis,pfr=row['gsis_id'],row['pfr_id']
        if not re.fullmatch('00-[0-9]{7}',gsis) or not re.fullmatch('[A-Za-z0-9]{1,20}',pfr):continue
        by_gsis.setdefault(gsis,[]).append(pfr);pfr_counts[pfr]+=1
    players={};pfr_to_gsis={}
    for player in data['players']:
        gsis=player['player_id'];pfr=player['pfr_player_id']
        if (gsis in players or pfr in pfr_to_gsis or by_gsis.get(gsis)!=[pfr] or pfr_counts[pfr]!=1):
            raise ValueError('Player identity is missing or ambiguous')
        players[gsis]=player;pfr_to_gsis[pfr]=gsis
    stats={};snaps={};excluded=Counter()
    for kind,records in (('stats',data['stats']),('snaps',data['snaps'])):
        seen=set()
        for item in records:
            row=item['stat' if kind=='stats' else 'snap']
            gsis=row['player_id'] if kind=='stats' else pfr_to_gsis[row['pfr_player_id']]
            if gsis not in players:raise ValueError('Unexpected player outside audit scope')
            stamp=_timestamp(row['source_observed_at'])
            digest=stat_row_sha256('nfl',row) if kind=='stats' else row_sha256({k:row[k] for k in SNAP_FIELDS})
            if (row['source_provider']!='nflverse' or digest!=row['source_record_sha256']
                    or not re.fullmatch('[0-9a-f]{64}',row['source_sha256']) or stamp>observed):
                raise ValueError('Invalid history or participation commitment')
            season,week=row['season'],row['week']
            if type(season) is not int or type(week) is not int or not 1<=week<=18:
                raise ValueError('Invalid regular-season history identity')
            day=date.fromisoformat(item['game_date'])
            home,away=item['home_team'],item['away_team']
            expected=f'{season}_{week:02}_{away}_{home}'
            if (home==away or row['team'] not in (home,away) or item['game_id']!=expected
                    or (kind=='snaps' and (row['game_id']!=expected or row['opponent'] not in {home,away}-{row['team']}))
                    or stamp.date()<day):
                raise ValueError('History does not match exact game identity')
            key=(gsis,season,week)
            if key in seen:raise ValueError('Duplicate player-week evidence')
            seen.add(key)
            if season<floor or day>=cutoff:
                excluded[kind+'_outside_cutoff']+=1;continue
            normalized=dict(player_id=gsis,season=season,week=week,day=day.isoformat(),game_id=expected,team=row['team'])
            if kind=='stats':stats[key]=normalized|{'row':row}
            else:
                if type(row['offense_snaps']) is not int or row['offense_snaps']<0:
                    raise ValueError('Invalid offensive participation count')
                if row['offense_snaps']==0:
                    excluded['zero_offense_snaps']+=1;continue
                snaps[key]=normalized|{'offense_snaps':row['offense_snaps']}
    missing=[];summaries=[]
    for gsis,player in players.items():
        player_stats={k:v for k,v in stats.items() if k[0]==gsis}
        player_snaps={k:v for k,v in snaps.items() if k[0]==gsis}
        missing_keys=sorted(set(player_snaps)-set(player_stats),key=lambda k:(k[1],k[2]))
        for key in missing_keys:
            missing.append(player_snaps[key]|dict(player=player['player'],current_quoted=player['current_quoted'],outcome='unknown'))
        model_keys=sorted(player_stats,key=lambda k:(k[1],k[2]),reverse=True)[:40]
        oldest=min((k[1],k[2]) for k in model_keys) if model_keys else None
        inside=[k for k in missing_keys if oldest is not None and (k[1],k[2])>=oldest]
        latest=sorted(set(player_stats)|set(player_snaps),key=lambda k:(k[1],k[2]),reverse=True)[:40]
        unknown=sum(k not in player_stats for k in latest)
        summaries.append(dict(player_id=gsis,player=player['player'],current_quoted=player['current_quoted'],
            recorded_stat_games=len(player_stats),verified_offensive_games=len(player_snaps),
            missing_stat_games=len(missing_keys),missing_inside_recorded_span=len(inside),
            recorded_last40_count=len(model_keys),union_last40_count=len(latest),union_last40_unknown=unknown,
            union_last40_known=len(latest)-unknown,
            null_receiving_categories=sum(v['row']['receiving_yards'] is None or v['row']['receptions'] is None for v in player_stats.values())))
    current=[r for r in summaries if r['current_quoted']]
    return dict(audit_version='nfl-participation-coverage-v1',observed_at=observed.isoformat(),cutoff=cutoff.isoformat(),season_floor=floor,
        scope='Selected quoted players and historical missing-result cases; not league-wide.',
        interpretation='Missing stats are unknown outcomes, not zeroes. Union windows are a coverage diagnostic, not replacement model inputs.',
        players=len(players),current_quoted_players=len(current),verified_stat_rows=len(stats),verified_offensive_rows=len(snaps),
        missing_stat_games=len(missing),current_quoted_missing_stat_games=sum(r['missing_stat_games'] for r in current),
        current_quoted_players_with_missing=sum(r['missing_stat_games']>0 for r in current),
        excluded=dict(sorted(excluded.items())),player_coverage=sorted(summaries,key=lambda r:(not r['current_quoted'],-r['missing_stat_games'],r['player'])),
        missing_games=sorted(missing,key=lambda r:(r['player'],r['season'],r['week'])),
        invented_stat_rows=0,published_forecasts=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--identity-bundle',type=Path,help='Existing archived source bundle containing the committed crosswalk')
    args=parser.parse_args()
    try:
        raw=args.input.read_bytes();data=json.loads(gzip.decompress(raw) if args.input.suffix=='.gz' else raw)
        if args.identity_bundle is not None:
            identity_raw=args.identity_bundle.read_bytes()
            identity_bundle=json.loads(gzip.decompress(identity_raw) if args.identity_bundle.suffix=='.gz' else identity_raw)
            if data.get('identity_source_sha256')!=identity_bundle['identity']['source_sha256']:
                raise ValueError('Referenced identity bundle does not match audit input')
            data['identity']=identity_bundle['identity']
        result=audit(data);result['input_sha256']=hashlib.sha256(raw).hexdigest()
        print(json.dumps(result,indent=2,sort_keys=True))
    except Exception as exc:
        raise SystemExit(f'NFL history coverage unavailable: {type(exc).__name__}') from None


if __name__=='__main__':main()
