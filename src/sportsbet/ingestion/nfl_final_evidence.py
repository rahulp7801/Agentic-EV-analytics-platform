"""Recover missing NFL receiving results from archived, explicit final evidence.

No fetching, history ingestion, or inferred zeroes. The bundle is collected from
free ESPN event/roster/athlete endpoints and the published nflverse ID crosswalk.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sportsbet.ingestion.provenance import stat_row_sha256
from sportsbet.ledger import utc_timestamp, verified_settlement_evidence, VERIFIED_SETTLEMENT_SOURCE
from sportsbet.schedules import scheduled_stat_teams
from sportsbet.settlement import _candidate

CORE='sports.core.api.espn.com'
BASE='/v2/sports/football/leagues/nfl'
IDENTITY_URL='https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _reference(value, path):
    parts=urlsplit(value)
    if (parts.scheme not in ('http','https') or parts.netloc!=CORE or parts.path!=path
            or parts.fragment or parts.query not in ('','lang=en&region=us')):
        raise ValueError('Mismatched ESPN evidence reference')


def _integer(value):
    if type(value) not in (int,float) or not Decimal(str(value)).is_finite() or int(value)!=value:
        raise ValueError('Explicit integer stat required')
    return int(value)


def _stat(data, category, name):
    categories=[c for c in data['splits']['categories'] if c['name']==category]
    cat,=categories
    stat,=[s for s in cat['stats'] if s['name']==name]
    return _integer(stat['value'])


def inspect_bundle(bundle: dict, *, now: datetime | None = None) -> list[dict]:
    """Return validated per-player final evidence; DNPs retain unknown outcomes."""
    now=now or datetime.now(timezone.utc)
    identity=bundle['identity']
    if identity['url']!=IDENTITY_URL or digest(identity['response_text'])!=identity['source_sha256']:
        raise ValueError('Invalid identity commitment')
    if utc_timestamp(identity['retrieved_at'])>now:
        raise ValueError('Future identity observation')
    mapping={};seen_espn=set()
    reader=csv.DictReader(io.StringIO(identity['response_text']))
    for row in reader:
        gsis,espn=row['gsis_id'],row['espn_id']
        if not re.fullmatch(r'00-[0-9]{7}',gsis) or not re.fullmatch(r'[1-9][0-9]*',espn):
            continue
        if gsis in mapping or espn in seen_espn:
            raise ValueError('Ambiguous player crosswalk')
        mapping[gsis]=espn;seen_espn.add(espn)
    sources={}
    for source in bundle['sources']:
        if (source['url'] in sources or digest(source['response_text'])!=source['sha256']
                or utc_timestamp(source['observed_at'])>now):
            raise ValueError('Invalid source commitment or observation')
        sources[source['url']]=source
    def read(url):
        source=sources[url]
        return json.loads(source['response_text']),source
    results=[];seen=set()
    for player in bundle['players']:
        event=player['espn_event_id'];gsis=player['player_id'];espn=mapping[gsis]
        if not re.fullmatch(r'[1-9][0-9]*',event) or (event,gsis) in seen:
            raise ValueError('Invalid or duplicate recovery identity')
        seen.add((event,gsis))
        summary,summary_source=read(f'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event}')
        header=summary['header'];comp,=header['competitions']
        if (header['id']!=event or comp['id']!=event or header['league']['slug']!='nfl'
                or comp['status']['type']['completed'] is not True
                or header['season']['type']!=2):
            raise ValueError('Exact completed regular-season game required')
        season=_integer(header['season']['year']);week=_integer(header['week'])
        start=utc_timestamp(comp['date']);day=start.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        if day!=player['date'] or not 1<=week<=18 or season!=(start.year if start.month>=9 else start.year-1):
            raise ValueError('Invalid recovery game date or week')
        teams=comp['competitors']
        home,=[t for t in teams if t['homeAway']=='home'];away,=[t for t in teams if t['homeAway']=='away']
        if len(teams)!=2 or home['id']==away['id']:
            raise ValueError('Invalid game competitors')
        game=dict(provider_event_id=event,date=day,game_time=start.isoformat(),completed=True,
            home_name=home['team']['displayName'],away_name=away['team']['displayName'],
            home_abbr=home['team']['abbreviation'],away_abbr=away['team']['abbreviation'])
        scheduled_stat_teams('nfl',game)
        matches=[];receipts=[summary_source]
        for team in teams:
            tid=team['id'];path=f'{BASE}/events/{event}/competitions/{event}/competitors/{tid}/roster'
            roster,receipt=read(f'https://{CORE}{path}?limit=100')
            _reference(roster['$ref'],path);receipts.append(receipt)
            for entry in roster['entries']:
                if str(entry['playerId'])==espn:
                    matches.append((team,entry,path))
        team,entry,path=matches[0] if len(matches)==1 else (None,None,None)
        if entry is None:
            raise ValueError('Athlete must occur on exactly one event roster')
        _reference(entry['athlete']['$ref'],f'{BASE}/seasons/{season}/athletes/{espn}')
        if entry.get('period')!=0 or type(entry.get('didNotPlay')) is not bool:
            raise ValueError('Ambiguous game participation')
        result=dict(player_id=gsis,espn_player_id=espn,game=game)
        if entry['didNotPlay'] is True:
            result['status']='did_not_play';results.append(result);continue
        if entry.get('valid') is not True:
            raise ValueError('Invalid participation record')
        stat_path=f'{path}/{espn}/statistics/0'
        _reference(entry['statistics']['$ref'],stat_path)
        stat_url=entry['statistics']['$ref'].replace('http://','https://',1)
        stats,receipt=read(stat_url);receipts.append(receipt)
        _reference(stats['$ref'],stat_path)
        _reference(stats['competition']['$ref'],f'{BASE}/events/{event}/competitions/{event}')
        _reference(stats['athlete']['$ref'],f'{BASE}/seasons/{season}/athletes/{espn}')
        if stats['splits']['id']!='0' or stats['splits']['name']!='game' or _stat(stats,'general','gamesPlayed')!=1:
            raise ValueError('Explicit played full-game stats required')
        receptions=_stat(stats,'receiving','receptions');yards=_stat(stats,'receiving','receivingYards')
        if receptions<0 or (receptions==0 and yards!=0):
            raise ValueError('Inconsistent receiving totals')
        if any(not start<=utc_timestamp(r['observed_at'])<=now for r in receipts):
            raise ValueError('Final evidence predates game')
        abbr=team['team']['abbreviation'];abbr={'LAR':'LA','WSH':'WAS'}.get(abbr,abbr)
        row=dict(player_id=gsis,season=season,week=week,team=abbr,
            passing_yards=None,rushing_yards=None,receiving_yards=yards,receptions=receptions)
        commitments=[{k:r[k] for k in ('url','sha256','observed_at')} for r in receipts]
        result.update(status='verified_explicit_stats',stat_row=row,
            stat_record_sha256=stat_row_sha256('nfl',row),observed_at=max(utc_timestamp(r['observed_at']) for r in receipts).isoformat(),
            source_evidence=dict(version=1,espn_player_id=espn,gsis_player_id=gsis,
                did_not_play=False,games_played=1,identity_source_sha256=identity['source_sha256'],
                identity_source_url=IDENTITY_URL,sources=commitments))
        result['source_sha256']=digest(json.dumps(result['source_evidence'],sort_keys=True,separators=(',',':')))
        results.append(result)
    return results


def plan_recovery(rows: list[dict], evidence: list[dict]) -> dict:
    """Plan only unresolved exact receiving selections; never overwrite outcomes."""
    updates=[];pending=[]
    for p in rows:
        if p.get('outcome') is not None or p.get('sport')!='nfl' or p.get('prop_type') not in ('receptions','rec_yds'):
            continue
        matched=[]
        for item in evidence:
            if item['player_id']!=p.get('player_id'):continue
            try:
                candidate=_candidate(p,'nfl',[item['game']])
            except (KeyError,TypeError,ValueError,ArithmeticError):
                continue
            if candidate and utc_timestamp(p['game_start_time'])==utc_timestamp(item['game']['game_time']):
                matched.append((item,candidate))
        if len(matched)!=1:continue
        item,(game,day,line)=matched[0]
        if item['status']=='did_not_play':
            pending.append(p['prediction_id']);continue
        column='receptions' if p['prop_type']=='receptions' else 'receiving_yards'
        actual=item['stat_row'][column]
        outcome='push' if actual==line else ((actual>line)==(p['direction']=='over'))
        proof=dict(schedule_identity_version=2,**{k:game[k] for k in ('provider_event_id','date','home_abbr','away_abbr','home_name','away_name','completed','game_time')},
            player_id=p['player_id'],prop_type=p['prop_type'],actual_value=str(actual),stat_provider='espn',
            stat_source_sha256=item['source_sha256'],stat_record_sha256=item['stat_record_sha256'],
            stat_observed_at=item['observed_at'],stat_row=item['stat_row'],explicit_final_source=item['source_evidence'])
        ref=f"espn_schedule+espn:{game['provider_event_id']}:sha256:{digest(json.dumps(proof,sort_keys=True,separators=(',',':')))}"
        if not verified_settlement_evidence(p,outcome,VERIFIED_SETTLEMENT_SOURCE,ref,item['observed_at'],actual,proof):
            raise ValueError('Recovery failed existing settlement proof contract')
        updates.append(dict(prediction_id=p['prediction_id'],outcome=outcome,actual=actual,source_ref=ref,
            observed_at=item['observed_at'],evidence=proof,payload=p))
    return dict(updates=updates,did_not_play_pending=pending)
