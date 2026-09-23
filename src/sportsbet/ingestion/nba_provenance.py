"""Recover missing NBA provenance from matching official season responses."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import bindparam, select, update

from sportsbet.db.models import NBAPlayerGameLog
from sportsbet.ingestion.archive import write_archive
from sportsbet.ingestion.provenance import row_sha256, stat_batch_sha256, stat_row_sha256

SOURCE_URL='https://stats.nba.com/stats/playergamelogs'
FIELDS=('player_id','game_id','player_name','team_abbreviation','game_date','season',
    'is_home','opponent_team','minutes','points','rebounds','assists','threes_made','steals','blocks')
PROVENANCE=('source_sha256','source_record_sha256','source_observed_at')
STAT_COLUMNS={'PTS':'points','REB':'rebounds','AST':'assists','FG3M':'threes_made','STL':'steals','BLK':'blocks'}


def official_rows(response: str, season: int, observed: datetime) -> list[dict]:
    if (type(season) is not int or not 2000<=season<=2100 or observed.utcoffset() is None
            or observed>datetime.now(timezone.utc)):
        raise ValueError('Invalid source season or observation time')
    if len(response.encode('utf-8'))>64_000_000:
        raise ValueError('Official response exceeds limit')
    body=json.loads(response);params=body['parameters']
    expected={'SeasonYear':f'{season}-{str(season+1)[-2:]}','SeasonType':'Regular Season',
        'MeasureType':'Base','PerMode':'Totals','LeagueID':'00'}
    if any(params.get(k)!=v for k,v in expected.items()):
        raise ValueError('Unexpected official source scope')
    tables=[t for t in body['resultSets'] if t['name']=='PlayerGameLogs']
    if len(tables)!=1:
        raise ValueError('Ambiguous official result table')
    table=tables[0];headers=table['headers'];values=table['rowSet']
    required={'PLAYER_ID','PLAYER_NAME','GAME_ID','GAME_DATE','TEAM_ABBREVIATION','MATCHUP','MIN',*STAT_COLUMNS}
    if (not isinstance(headers,list) or len(headers)!=len(set(headers)) or not required<=set(headers)
            or not isinstance(values,list) or not 1<=len(values)<=100000):
        raise ValueError('Invalid official result shape')
    result=[];seen=set()
    for values_row in values:
        raw=dict(zip(headers,values_row,strict=True))
        player=raw['PLAYER_ID'];game=raw['GAME_ID'];name=raw['PLAYER_NAME'];team=raw['TEAM_ABBREVIATION']
        if (type(player) is not int or not 0<player<=2147483647 or not isinstance(game,str)
                or not re.fullmatch(f'002{str(season)[-2:]}[0-9]{{5}}',game)
                or not isinstance(name,str) or not 0<len(name)<=100 or any(ord(c)<32 for c in name)
                or not isinstance(team,str) or not re.fullmatch('[A-Z]{2,3}',team)):
            raise ValueError('Invalid official player/game identity')
        if (player,game) in seen:
            raise ValueError('Duplicate official player/game identity')
        seen.add((player,game))
        stamp=datetime.fromisoformat(raw['GAME_DATE'])
        day=stamp.date()
        if not date(season,7,1)<=day<=min(date(season+1,6,30),observed.date()):
            raise ValueError('Official game is outside the observed season')
        matchup=re.fullmatch(re.escape(team)+r' (vs\.|@) ([A-Z]{2,3})',raw['MATCHUP'])
        if not matchup or matchup[2]==team:
            raise ValueError('Invalid official matchup')
        minutes=Decimal(str(raw['MIN']))
        if not minutes.is_finite() or not 0<=minutes<=Decimal('999.9'):
            raise ValueError('Invalid official playing time')
        stats={target:raw[source] for source,target in STAT_COLUMNS.items()}
        if any(type(value) is not int or not 0<=value<=32767 for value in stats.values()):
            raise ValueError('Invalid official counting stat')
        result.append(dict(player_id=player,game_id=game,player_name=name,team_abbreviation=team,
            game_date=day,season=season,is_home=matchup[1]=='vs.',opponent_team=matchup[2],
            minutes=minutes.quantize(Decimal('.1'),rounding=ROUND_HALF_UP),**stats))
    return result


def value_digest(rows: list[dict]) -> str:
    """Commit all model values and identities; display names are reported separately."""
    hashes=[row_sha256({key:row[key] for key in FIELDS if key!='player_name'})
        for row in sorted(rows,key=lambda row:(row['player_id'],row['game_id']))]
    return hashlib.sha256(json.dumps(hashes,separators=(',',':')).encode()).hexdigest()


def recovery_plan(stored: list[dict], source: list[dict], season: int, observed: datetime) -> tuple[list[dict],dict]:
    index={(r['player_id'],r['game_id']):r for r in source}
    if len(index)!=len(source) or any(r['season']!=season for r in source+stored):
        raise ValueError('Ambiguous recovery season or source identities')
    if len({(r['player_id'],r['game_id']) for r in stored})!=len(stored):
        raise ValueError('Ambiguous stored identities')
    batch=stat_batch_sha256('nba','nba',season,[stat_row_sha256('nba',row) for row in source])
    counts=Counter();mismatches=Counter();updates=[]
    for previous in stored:
        current=index.get((previous['player_id'],previous['game_id']))
        if previous['source_provider']!='nba':counts['different_provider']+=1;continue
        if any(previous.get(key) is not None for key in PROVENANCE[:2]):
            counts['existing_provenance']+=1;continue
        if current is None:counts['missing_source']+=1;continue
        prior_observed=previous.get('source_observed_at')
        prior_utc=(prior_observed.replace(tzinfo=timezone.utc) if prior_observed.utcoffset() is None
            else prior_observed.astimezone(timezone.utc)) if prior_observed else None
        if prior_utc and prior_utc>observed:
            counts['observation_after_source']+=1;continue
        different=[key for key in FIELDS if key!='player_name' and previous[key]!=current[key]]
        if different:
            counts['value_mismatch']+=1;mismatches.update(different);continue
        updates.append({**{'expected_'+key:previous[key] for key in FIELDS},
            'expected_source_observed_at':prior_observed,
            'new_player_name':current['player_name'],'batch_digest':batch,
            'record_digest':stat_row_sha256('nba',current),'observed':observed})
        counts['recoverable']+=1
        if prior_observed is not None:counts['timestamp_only_recovered']+=1
        counts['name_updates']+=previous['player_name']!=current['player_name']
    report=dict(season=season,stored_rows=len(stored),official_rows=len(source),counts=dict(counts),
        mismatch_fields=dict(mismatches),values_sha256=value_digest(stored),
        normalized_source_sha256=batch,source_observed_at=observed.isoformat())
    return updates,report


def apply_plan(conn, updates: list[dict]) -> int:
    """Optimistic all-field comparison; any changed row aborts the outer transaction."""
    table=NBAPlayerGameLog.__table__
    statement=update(table).where(table.c.source_provider=='nba',
        *(table.c[key].is_(None) for key in PROVENANCE[:2]),
        table.c.source_observed_at.is_not_distinct_from(bindparam('expected_source_observed_at')),
        # These stable identities are non-null and have a unique B-tree index.
        # Null-safe identity comparisons force a full-table scan for each row.
        *(table.c[key]==bindparam('expected_'+key) for key in ('player_id','game_id')),
        *(table.c[key].is_not_distinct_from(bindparam('expected_'+key))
            for key in FIELDS if key not in ('player_id','game_id'))).values(
        player_name=bindparam('new_player_name'),source_sha256=bindparam('batch_digest'),
        source_record_sha256=bindparam('record_digest'),source_observed_at=bindparam('observed'))
    for offset in range(0,len(updates),500):
        batch=updates[offset:offset+500]
        if conn.execute(statement,batch).rowcount!=len(batch):
            raise ValueError('History changed during recovery; transaction must roll back')
    return len(updates)


def recover_response(engine, response: str, season: int, observed: datetime, *, apply: bool = False) -> dict:
    source=official_rows(response,season,observed)
    table=NBAPlayerGameLog.__table__
    with engine.begin() as conn:
        if conn.dialect.name=='postgresql':
            conn.exec_driver_sql('SET LOCAL statement_timeout=60000')
            conn.exec_driver_sql('SET LOCAL lock_timeout=5000')
            if not apply:conn.exec_driver_sql('SET TRANSACTION READ ONLY')
        stored=[dict(row) for row in conn.execute(select(table).where(table.c.season==season)).mappings()]
        updates,report=recovery_plan(stored,source,season,observed)
        report.update(applied=False,updated_rows=0,raw_response_sha256=hashlib.sha256(response.encode()).hexdigest(),
            source_url=SOURCE_URL)
        if apply:
            # Retain the exact source response and plan before changing any provenance.
            archive=write_archive(dict(report=report,response=json.loads(response)),directory=Path('.local/nba-provenance'))
            report['archive']=str(archive)
            report['updated_rows']=apply_plan(conn,updates)
            after=[dict(row) for row in conn.execute(select(table).where(table.c.season==season)).mappings()]
            if value_digest(after)!=report['values_sha256']:
                raise ValueError('Model values changed during recovery')
            report['applied']=True
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season',required=True,type=int)
    parser.add_argument('--apply',action='store_true',help='Attach verified metadata; default is read-only audit')
    args=parser.parse_args()
    engine=None
    try:
        from nba_api.stats.endpoints import PlayerGameLogs
        from sportsbet.db.connection import get_sync_engine
        logs=PlayerGameLogs(season_nullable=f'{args.season}-{str(args.season+1)[-2:]}',
            season_type_nullable='Regular Season',timeout=20)
        observed=datetime.now(timezone.utc)
        engine=get_sync_engine()
        print(json.dumps(recover_response(engine,logs.get_json(),args.season,observed,apply=args.apply),sort_keys=True))
    except Exception as exc:
        raise SystemExit(f'NBA provenance recovery failed ({type(exc).__name__})') from None
    finally:
        if engine is not None:engine.dispose()


if __name__=='__main__':
    main()
