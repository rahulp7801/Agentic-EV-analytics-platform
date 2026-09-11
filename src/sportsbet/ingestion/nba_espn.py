"""Bounded ESPN fallback with verified NBA identifiers and protected official rows."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from sportsbet.db.models import NBAPlayerGameLog
from sportsbet.ingestion.archive import write_archive

CROSSWALKS = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/nba_crosswalk'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'


def index_rows(rows: list[dict], key: str, required: tuple[str, ...], method: str, year: int) -> dict:
    result={}
    for row in rows:
        if row.get('season')!=str(year):
            raise ValueError('Crosswalk season mismatch')
        if row.get('match_confidence')!='1' or row.get('match_method')!=method:
            continue  # Never promote fuzzy/unmatched identifier suggestions.
        if not all(row.get(field) for field in (key,*required)):
            continue
        identity=row[key]
        if identity in result and any(result[identity][field]!=row[field] for field in required):
            raise ValueError('Ambiguous crosswalk identity')
        result[identity]=row
    if not result:
        raise ValueError('No verified crosswalk identities')
    target_ids=[row[required[0]] for row in result.values()]
    if len(set(target_ids))!=len(target_ids):
        raise ValueError('Crosswalk target has multiple source identities')
    return result


def normalize_name(name: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD',name) if not unicodedata.combining(c)).casefold().strip()


def official_names(rows) -> dict:
    names={}
    for identity,name in rows:
        names.setdefault(normalize_name(name),{})[int(identity)]=name
    return names


def parse_game(data: dict, season: int, game: dict, players: dict, teams: dict,
               source_hash: str, received: datetime, names: dict | None = None) -> list[dict]:
    header=data['header']
    competition,=header['competitions']
    if competition['status']['type']['completed'] is not True:
        raise ValueError('Expected a final box score')
    if header['season']['year']!=season+1 or header['season']['type']!=2:
        raise ValueError('Expected the requested regular season')
    if str(header['id'])!=game['espn_game_id'] or not re.fullmatch(f'002{str(season)[-2:]}[0-9]{{5}}',game['nba_game_id']):
        raise ValueError('Box score does not match the NBA game identity')
    start=datetime.fromisoformat(competition['date'].replace('Z','+00:00'))
    if start.utcoffset() is None or start>received:
        raise ValueError('Invalid final game timestamp')
    day=start.astimezone(ZoneInfo('America/New_York')).date()
    if str(day)!=game['game_date']:
        raise ValueError('Crosswalk date mismatch')
    home,=[str(t['id']) for t in competition['competitors'] if t['homeAway']=='home']
    away,=[str(t['id']) for t in competition['competitors'] if t['homeAway']=='away']
    if (home,away)!=(game['home_espn_team_id'],game['away_espn_team_id']):
        raise ValueError('Crosswalk team mismatch')
    if teams[home]['nba_team_id']!=game['nba_home_team_id'] or teams[away]['nba_team_id']!=game['nba_away_team_id']:
        raise ValueError('Conflicting team crosswalk')
    if len(data['boxscore']['players'])!=2 or {str(t['team']['id']) for t in data['boxscore']['players']}!={home,away}:
        raise ValueError('Incomplete box-score teams')
    if any(not re.fullmatch('[A-Z]{2,3}',teams[t]['nba_team_abbreviation']) for t in (home,away)):
        raise ValueError('Invalid NBA team abbreviation')
    rows=[];seen=set()
    for team in data['boxscore']['players']:
        team_id=str(team['team']['id'])
        group,=team['statistics']
        if len(set(group['keys']))!=len(group['keys']):
            raise ValueError('Duplicate box-score stat keys')
        count=0
        for entry in group['athletes']:
            if entry.get('didNotPlay') is True:
                continue
            mapping=players.get(str(entry['athlete']['id']))
            if not mapping and names is not None:
                matches=names.get(normalize_name(entry['athlete']['displayName']),{})
                if len(matches)==1:
                    identity,name=next(iter(matches.items()))
                    mapping={'nba_player_id':str(identity),'nba_player_name':name}
            if not mapping or not mapping['nba_player_id'].isdigit():
                raise ValueError('Participating player has no verified NBA identity')
            player_id=int(mapping['nba_player_id'])
            if not 0<player_id<=2147483647 or player_id in seen:
                raise ValueError('Invalid or duplicate NBA player identity')
            seen.add(player_id)
            values=dict(zip(group['keys'],entry['stats'],strict=True))
            stats={}
            for key in ('points','rebounds','assists','steals','blocks'):
                raw=values[key]
                if not isinstance(raw,str) or not re.fullmatch(r'[0-9]+',raw) or int(raw)>32767:
                    raise ValueError('Missing or invalid counting stat')
                stats[key]=int(raw)
            threes=re.fullmatch(r'([0-9]+)-([0-9]+)',values['threePointFieldGoalsMade-threePointFieldGoalsAttempted'])
            if not threes or not int(threes[1])<=int(threes[2])<=32767:
                raise ValueError('Invalid three-point stat')
            stats['threes_made']=int(threes[1])
            minutes=values['minutes']
            if not re.fullmatch(r'[0-9]+(?::[0-5][0-9])?',minutes):
                raise ValueError('Missing or invalid playing time')
            pieces=minutes.split(':')
            stats['minutes']=int(pieces[0])+(int(pieces[1])/60 if len(pieces)==2 else 0)
            if stats['minutes']>999.9:
                raise ValueError('Playing time exceeds storage bounds')
            rows.append(dict(player_id=player_id,player_name=mapping['nba_player_name'],
                game_id=game['nba_game_id'],game_date=day,season=season,
                team_abbreviation=teams[team_id]['nba_team_abbreviation'],is_home=team_id==home,
                opponent_team=teams[away if team_id==home else home]['nba_team_abbreviation'],
                **stats,source_provider='espn',source_sha256=source_hash,source_observed_at=received))
            count+=1
        if count<5:
            raise ValueError('Incomplete participating-player box score')
    return rows


def store_rows(engine, rows: list[dict]) -> None:
    if not rows:
        return
    table=NBAPlayerGameLog.__table__
    statement=insert(table)
    statement=statement.on_conflict_do_update(index_elements=['player_id','game_id'],
        set_={key:statement.excluded[key] for key in rows[0] if key not in ('player_id','game_id')},
        where=table.c.source_provider=='espn')
    # A failed batch never publishes partially refreshed history. NBA rows take priority.
    with engine.begin() as conn:
        incoming={(r['player_id'],r['game_id']) for r in rows}
        previous=set(conn.execute(select(table.c.player_id,table.c.game_id).where(
            table.c.source_provider=='espn',table.c.game_id.in_({r['game_id'] for r in rows}))).all())
        if not previous<=incoming:
            raise ValueError('Provider removed a previously recorded participant; official reconciliation required')
        conn.execute(statement,rows)


def refresh_recent(season: int, today: date, engine) -> dict:
    first=today-timedelta(days=6)
    sources=[];rows=[];processed=set()
    with httpx.Client(timeout=20,follow_redirects=True) as client:
        def fetch(url: str) -> tuple[str, str]:
            response=client.get(url)
            response.raise_for_status()
            if response.url.scheme!='https':
                raise ValueError('Source requires HTTPS')
            digest=hashlib.sha256(response.content).hexdigest()
            sources.append(dict(url=url,retrieved_at=datetime.now(timezone.utc).isoformat(),sha256=digest,body=response.text))
            time.sleep(1)
            return response.text,digest

        year=season+1
        tables={kind:list(csv.DictReader(io.StringIO(fetch(f'{CROSSWALKS}/nba_{kind}_crosswalk_{year}.csv')[0])))
                for kind in ('schedule','player','team')}
        games=index_rows(tables['schedule'],'espn_game_id',('nba_game_id','game_date','home_espn_team_id',
            'away_espn_team_id','nba_home_team_id','nba_away_team_id'),'both',year)
        players=index_rows(tables['player'],'espn_athlete_id',('nba_player_id','nba_player_name'),'exact_name',year)
        teams=index_rows(tables['team'],'espn_team_id',('nba_team_id','nba_team_abbreviation'),'exact_name',year)
        with engine.connect() as conn:
            known=set(conn.execute(text('SELECT game_id FROM nba_player_gamelogs WHERE season=:season GROUP BY game_id HAVING count(*)>=10 AND count(DISTINCT team_abbreviation)=2'),{'season':season}).scalars())
            identities=conn.execute(text("SELECT DISTINCT player_id,player_name FROM nba_player_gamelogs WHERE source_provider='nba' AND player_name IS NOT NULL")).all()
        names=official_names(identities)
        prefix='002'+str(season)[-2:]
        missing=[g for g in tables['schedule'] if g.get('nba_game_id','').startswith(prefix)
            and g['game_date']<str(first) and g['nba_game_id'] not in known]
        if missing:
            raise ValueError('History gap predates the seven-day fallback window; backfill required')
        for offset in range(7):
            day=first+timedelta(days=offset)
            board=json.loads(fetch(f'{ESPN}/scoreboard?dates={day:%Y%m%d}&limit=1000')[0])
            for event in board['events']:
                identity=str(event['id'])
                if identity in processed or event['status']['type']['completed'] is not True:
                    continue
                season_type=event['season']['type']
                if season_type not in (1,2,3,4,5):
                    raise ValueError('Unknown ESPN season type')
                if season_type!=2:
                    continue
                if identity not in games or not identity.isdigit():
                    raise ValueError('Completed game has no verified NBA identity')
                if not games[identity]['nba_game_id'].startswith(prefix):
                    continue  # Exclude preseason, playoffs and the non-season Cup final.
                body,digest=fetch(f'{ESPN}/summary?event={identity}')
                parsed=parse_game(json.loads(body),season,games[identity],players,teams,digest,datetime.now(timezone.utc),names)
                if any(not first<=row['game_date']<=today for row in parsed):
                    raise ValueError('Box score is outside the requested window')
                rows.extend(parsed);processed.add(identity)
        pending=[g for g in games.values() if g['nba_game_id'].startswith(prefix)
            and str(first)<=g['game_date']<str(today) and g['nba_game_id'] not in known and g['espn_game_id'] not in processed]
        if pending:
            raise ValueError('Recent scheduled games have no verified final history')
    report=dict(provider='espn',season=season,checked_from=str(first),checked_through=str(today),
        games=len(processed),rows=len(rows),prior_game_count=len(known),captured_at=datetime.now(timezone.utc).isoformat(),
        scope='Seven-day final regular-season updates; verified crosswalk or unique official name identities. Existing NBA rows take priority.')
    archive=write_archive(dict(report=report,sources=sources,
        official_player_identities=[list(row) for row in identities],
        rows=[{key:value.isoformat() if isinstance(value,(date,datetime)) else value for key,value in row.items()} for row in rows]),
        directory=Path('.local/nba-refresh'))
    store_rows(engine,rows)
    return report | {'archive':str(archive)}
