"""Stable hashes for the exact normalized stat rows written to storage."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
import re

LEGACY_NFL_STAT_FIELDS=(
    'player_id','season','week','team','passing_yards','rushing_yards','receiving_yards')

STAT_FIELDS={
    'nba':('player_id','game_id','game_date','team_abbreviation','points','rebounds','assists'),
    'nfl':LEGACY_NFL_STAT_FIELDS+('receptions',),
}


def _canonical(value):
    if hasattr(value,'item') and callable(value.item):
        value=value.item()
    if value is None or type(value) in (bool,int,str):
        return value
    if isinstance(value,float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError('Stat evidence contains a non-finite number')
        decimal=Decimal(str(value))
        return int(decimal) if decimal==decimal.to_integral_value() else str(decimal.normalize())
    if isinstance(value,Decimal):
        if not value.is_finite():
            raise ValueError('Stat evidence contains a non-finite decimal')
        return int(value) if value==value.to_integral_value() else str(value.normalize())
    if isinstance(value,datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Stat evidence timestamp requires a timezone')
        return value.isoformat()
    if isinstance(value,date):
        return value.isoformat()
    raise ValueError('Stat evidence contains an unsupported value')


def row_sha256(row: Mapping[str, object]) -> str:
    """Hash one normalized stored row before provenance columns are attached."""
    if not row or any(not isinstance(key,str) or key.startswith('source_') for key in row):
        raise ValueError('Stat evidence row is invalid')
    payload={key:_canonical(row[key]) for key in sorted(row)}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def stat_row_sha256(
    sport: str,
    row: Mapping[str, object],
    *,
    legacy_nfl: bool = False,
) -> str:
    """Hash one stored stat row, retaining the pre-receptions NFL format.

    New NFL ingestion commits ``receptions`` to the row digest. A row that does
    not contain that field is hashed with the legacy field set so retained
    settlement evidence remains reproducible. Callers validating a stored row
    that includes receptions may explicitly request the legacy format for
    non-reception predictions recorded before this extension.
    """
    try:
        if legacy_nfl:
            if sport!='nfl':
                raise ValueError('Legacy stat evidence is only defined for NFL rows')
            fields=LEGACY_NFL_STAT_FIELDS
        else:
            fields=STAT_FIELDS[sport]
            if sport=='nfl' and 'receptions' not in row:
                fields=LEGACY_NFL_STAT_FIELDS
        selected={field:row[field] for field in fields}
    except (KeyError,TypeError):
        raise ValueError('Settlement stat evidence is incomplete') from None
    normalized={key:_canonical(value) for key,value in selected.items()}
    if sport=='nba':
        integers=('player_id','points','rebounds','assists')
        strings=('game_id','game_date','team_abbreviation')
    else:
        integers=('season','week','passing_yards','rushing_yards','receiving_yards')
        if 'receptions' in selected:
            integers+=('receptions',)
        strings=('player_id','team')
    if (any(normalized[key] is not None and type(normalized[key]) is not int for key in integers)
            or any(not isinstance(normalized[key],str) or not normalized[key].strip() for key in strings)):
        raise ValueError('Settlement stat evidence has invalid field types')
    nonnegative_fields=integers if sport=='nba' else ('season','week')
    if any(normalized[key] is not None and normalized[key] < 0 for key in nonnegative_fields):
        raise ValueError('Settlement stat evidence has negative values')
    return row_sha256(selected)


def stat_batch_sha256(provider: str, sport: str, season: int, record_hashes: list[str]) -> str:
    if ((provider,sport) not in (('nba','nba'),('nflverse','nfl'))
            or type(season) is not int or not record_hashes
            or any(not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value)
                for value in record_hashes)):
        raise ValueError('Stat evidence batch is invalid')
    payload=dict(provider=provider,sport=sport,season=season,records=sorted(record_hashes))
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
