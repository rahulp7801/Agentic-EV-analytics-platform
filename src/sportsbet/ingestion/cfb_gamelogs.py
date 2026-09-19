"""Ingest exact-ID CFB player game logs from public SportsDataverse releases."""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timezone

import httpx
import pandas as pd
import polars as pl
import sqlalchemy as sa

from sportsbet.ingestion.provenance import row_sha256
from sportsbet.ingestion.upsert import upsert_rows

BASE = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download'
MAX_ASSET_BYTES = 32_000_000
PLAYER_COLUMNS = {'game_id','season','team_id','category','athlete_id','athlete_name',
    'passingYards','rushingYards','receptions','receivingYards'}
SCHEDULE_COLUMNS = {'game_id','season','week','game_date','home_id','away_id','home_team','away_team',
    'home_abbreviation','away_abbreviation','status'}
TRUSTED_HOSTS = {'github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}


def asset_urls(season: int) -> tuple[str,str]:
    if type(season) is not int or not 2004 <= season <= 2100:
        raise ValueError('Invalid CFB season')
    return (
        f'{BASE}/espn_cfb_player_box/player_box_{season}.parquet',
        f'{BASE}/espn_cfb_schedules/cfb_schedule_{season}.parquet',
    )


def download_asset(client: httpx.Client, url: str) -> bytes:
    target=httpx.URL(url)
    for _ in range(4):
        if target.scheme!='https' or target.host not in TRUSTED_HOSTS or target.port not in (None,443) or target.userinfo:
            raise ValueError('Untrusted CFB asset URL')
        with client.stream('GET',target) as response:
            if response.is_redirect:
                location=response.headers.get('location')
                if not location:
                    raise ValueError('Invalid CFB asset redirect')
                target=target.join(location)
                continue
            response.raise_for_status()
            try:
                announced=int(response.headers.get('content-length','0'))
            except ValueError:
                raise ValueError('Invalid CFB asset length') from None
            if response.status_code!=200 or announced<0 or announced>MAX_ASSET_BYTES:
                raise ValueError('Invalid CFB asset response')
            chunks=[];size=0
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size>MAX_ASSET_BYTES:
                    raise ValueError('Invalid CFB asset response')
                chunks.append(chunk)
            payload=b''.join(chunks)
            if not payload:
                raise ValueError('Invalid CFB asset response')
            return payload
    raise ValueError('Too many CFB asset redirects')


def _integer(value, *, nonnegative: bool = False) -> int | None:
    if value is None:
        return None
    text=str(value).strip()
    if not re.fullmatch(r'-?[0-9]+',text):
        raise ValueError('Invalid CFB integer statistic')
    result=int(text)
    if nonnegative and result<0:
        raise ValueError('Invalid negative CFB count')
    return result


def normalize_assets(player_bytes: bytes, schedule_bytes: bytes, season: int,
                     observed_at: datetime | None = None) -> tuple[list[dict],dict]:
    if (not isinstance(player_bytes,bytes) or not isinstance(schedule_bytes,bytes)
            or not player_bytes or not schedule_bytes or len(player_bytes)>MAX_ASSET_BYTES
            or len(schedule_bytes)>MAX_ASSET_BYTES):
        raise ValueError('Invalid CFB asset bytes')
    observed_at=observed_at or datetime.now(timezone.utc)
    if observed_at.utcoffset() is None:
        raise ValueError('CFB observation time requires a timezone')
    try:
        players=pl.read_parquet(io.BytesIO(player_bytes))
        schedules=pl.read_parquet(io.BytesIO(schedule_bytes))
    except Exception as exc:
        raise ValueError('Invalid CFB parquet asset') from exc
    if not PLAYER_COLUMNS<=set(players.columns) or not SCHEDULE_COLUMNS<=set(schedules.columns):
        raise ValueError('CFB asset schema is incomplete')
    if players.height>500_000 or schedules.height>20_000:
        raise ValueError('CFB asset row limit exceeded')
    schedules=schedules.select(sorted(SCHEDULE_COLUMNS))
    if schedules['game_id'].n_unique()!=schedules.height:
        raise ValueError('Duplicate CFB schedule identity')
    schedule_by_game={int(row['game_id']):row for row in schedules.to_dicts()
        if row['status']=='STATUS_FINAL' and int(row['season'])==season}

    selected=players.select(sorted(PLAYER_COLUMNS))
    keys=['game_id','athlete_id','category']
    if selected.select(keys).unique().height!=selected.height:
        raise ValueError('Duplicate CFB player category identity')
    grouped={};skipped_team_aggregates=0
    for row in selected.to_dicts():
        if int(row['season'])!=season or int(row['game_id']) not in schedule_by_game:
            continue
        category=row['category']
        if category not in ('passing','rushing','receiving'):
            continue
        athlete_id=int(row['athlete_id']);team_id=int(row['team_id'])
        name=row['athlete_name']
        if athlete_id<0 and isinstance(name,str) and name.strip()=='Team':
            skipped_team_aggregates+=1
            continue
        if athlete_id<=0 or team_id<=0 or not isinstance(name,str) or not name.strip() or len(name)>100:
            raise ValueError('Invalid CFB player identity')
        key=(int(row['game_id']),athlete_id)
        current=grouped.setdefault(key,dict(game_id=key[0],athlete_id=athlete_id,
            player_name=name.strip(),team_id=team_id,passing_yards=None,rushing_yards=None,
            receiving_yards=None,receptions=None))
        if current['player_name']!=name.strip() or current['team_id']!=team_id:
            raise ValueError('Conflicting CFB player identity')
        if category=='passing':current['passing_yards']=_integer(row['passingYards'])
        elif category=='rushing':current['rushing_yards']=_integer(row['rushingYards'])
        else:
            current['receiving_yards']=_integer(row['receivingYards'])
            current['receptions']=_integer(row['receptions'],nonnegative=True)

    player_hash=hashlib.sha256(player_bytes).hexdigest()
    schedule_hash=hashlib.sha256(schedule_bytes).hexdigest()
    source_hash=hashlib.sha256(json.dumps({'player':player_hash,'schedule':schedule_hash},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    records=[]
    for key,row in sorted(grouped.items()):
        game=schedule_by_game[key[0]]
        home=int(game['home_id'])==row['team_id'];away=int(game['away_id'])==row['team_id']
        if home==away:
            raise ValueError('CFB player team does not match schedule')
        opponent_side='away' if home else 'home';team_side='home' if home else 'away'
        game_date=datetime.fromisoformat(game['game_date'].replace('Z','+00:00'))
        if game_date.utcoffset() is None:
            raise ValueError('CFB game date requires a timezone')
        identity_values=(game[team_side+'_team'],game[team_side+'_abbreviation'],
            game[opponent_side+'_team'],game[opponent_side+'_abbreviation'])
        if any(not isinstance(value,str) or not value.strip() or len(value)>100 for value in identity_values):
            raise ValueError('Invalid CFB schedule team identity')
        record=row|dict(season=season,week=int(game['week']),game_date=game_date.date(),is_home=home,
            team_name=game[team_side+'_team'],team_abbreviation=game[team_side+'_abbreviation'],
            opponent_id=int(game[opponent_side+'_id']),opponent_name=game[opponent_side+'_team'],
            opponent_abbreviation=game[opponent_side+'_abbreviation'])
        if not any(record[field] is not None for field in (
                'passing_yards','rushing_yards','receiving_yards','receptions')):
            continue
        record_hash=row_sha256(record)
        records.append(record|dict(source_provider='sportsdataverse_espn',source_sha256=source_hash,
            source_player_sha256=player_hash,source_schedule_sha256=schedule_hash,
            source_record_sha256=record_hash,source_observed_at=observed_at))
    if not records:
        raise ValueError('CFB assets contain no completed player game logs')
    return records,dict(provider='sportsdataverse_espn',season=season,rows=len(records),
        skipped_team_aggregates=skipped_team_aggregates,
        player_source_sha256=player_hash,schedule_source_sha256=schedule_hash,source_sha256=source_hash)


def ingest_cfb_gamelogs_season(season: int, engine: sa.Engine) -> dict:
    player_url,schedule_url=asset_urls(season)
    with httpx.Client(timeout=30,follow_redirects=False) as client:
        player_bytes=download_asset(client,player_url)
        schedule_bytes=download_asset(client,schedule_url)
    records,coverage=normalize_assets(player_bytes,schedule_bytes,season)
    pd.DataFrame.from_records(records).to_sql('cfb_player_gamelogs',engine,if_exists='append',
        index=False,chunksize=500,method=upsert_rows(['athlete_id','game_id']))
    return coverage
