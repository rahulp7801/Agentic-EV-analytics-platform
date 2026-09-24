"""Ingest exact NFL offensive and defensive participation from nflverse."""
from __future__ import annotations

from datetime import datetime, timezone

import nflreadpy as nfl
import polars as pl
import sqlalchemy as sa
import structlog

from sportsbet.db.connection import get_sync_engine
from sportsbet.ingestion.provenance import row_sha256, stat_batch_sha256
from sportsbet.ingestion.upsert import upsert_rows

log = structlog.get_logger()
FIELDS = ('game_id','season','week','player','pfr_player_id','position','team','opponent',
          'offense_snaps','defense_snaps')


def prepare_snap_counts(data: pl.DataFrame) -> pl.DataFrame:
    """Validate a season before writing; missing participation is never a zero.

    Existing complete rows keep their normalized fields and hash commitments.
    Invalid counts reject the season before its upsert transaction is opened.
    Legacy stored zeros remain ambiguous and are not reclassified here.
    """
    if 'game_type' in data.columns:
        data = data.filter(pl.col('game_type') == 'REG')
    if set(FIELDS) - set(data.columns):
        raise ValueError('Snap-count source schema is incomplete')
    data = data.select(FIELDS).drop_nulls(['game_id','pfr_player_id','team','opponent'])
    if data.is_empty():
        raise ValueError('Snap-count source contains no identified participation')
    for column in ('offense_snaps','defense_snaps'):
        counts = data[column]
        if not (counts.dtype.is_integer() or counts.dtype.is_float()):
            raise ValueError('Snap-count source requires explicit integer counts')
        valid = (counts.is_not_null() & counts.is_finite() & (counts >= 0)
                 & (counts <= 32767) & (counts == counts.floor()))
        if not valid.fill_null(False).all():
            raise ValueError('Snap-count source has missing or invalid participation')
    if data.select('game_id','pfr_player_id').is_duplicated().any():
        raise ValueError('Snap-count source has duplicate participant records')
    return data.rename({'player':'player_name'}).with_columns(
        pl.col('offense_snaps','defense_snaps').cast(pl.Int64,strict=True))


def ingest_snap_counts_seasons(seasons: list[int], engine: sa.Engine | None = None) -> None:
    """Upsert regular-season snap counts with row and batch commitments."""
    engine = engine or get_sync_engine()
    observed = datetime.now(timezone.utc)
    for season in seasons:
        data = nfl.load_snap_counts([season])
        frame = prepare_snap_counts(data).to_pandas()
        rows = frame.to_dict('records')
        hashes = [row_sha256(row) for row in rows]
        batch = stat_batch_sha256('nflverse','nfl',season,hashes)
        frame['source_provider'] = 'nflverse'
        frame['source_sha256'] = batch
        frame['source_record_sha256'] = hashes
        frame['source_observed_at'] = observed
        with engine.begin() as conn:
            frame.to_sql('nfl_snap_counts',conn,if_exists='append',index=False,chunksize=1000,
                         method=upsert_rows(['game_id','pfr_player_id']))
        log.info('snap_counts_load_done',season=season,rows=len(rows))
