from unittest.mock import MagicMock,patch

import pandas as pd
import polars as pl
import pytest

from sportsbet.ingestion.provenance import row_sha256,stat_batch_sha256
from sportsbet.ingestion.snap_counts import FIELDS,ingest_snap_counts_seasons,prepare_snap_counts


def source(**changes):
    row=dict(game_id='2026_01_A_B',season=2026,week=1,player='Fixture Player',pfr_player_id='FixtPl00',
        position='WR',team='A',opponent='B',offense_snaps=10.0,defense_snaps=0.0,game_type='REG')
    return pl.DataFrame([row|changes])


@pytest.mark.parametrize('column',['offense_snaps','defense_snaps'])
@pytest.mark.parametrize('value',[None,float('nan'),float('inf'),-float('inf'),-1.0,1.5,32768.0,True,'10'])
def test_invalid_participation_never_reaches_database(column,value):
    engine=MagicMock()
    with patch('sportsbet.ingestion.snap_counts.nfl.load_snap_counts',return_value=source(**{column:value})), \
         patch.object(pd.DataFrame,'to_sql') as write:
        with pytest.raises(ValueError,match='Snap-count source'):
            ingest_snap_counts_seasons([2026],engine)
    engine.begin.assert_not_called()
    write.assert_not_called()


def test_explicit_zero_and_integer_float_counts_keep_existing_commitments():
    data=source();normalized=prepare_snap_counts(data)
    legacy=data.select(FIELDS).rename({'player':'player_name'}).to_pandas()
    for column in ('offense_snaps','defense_snaps'):
        legacy[column]=legacy[column].fillna(0).astype('int64')
    assert normalized.to_dicts()==legacy.to_dict('records')
    expected=row_sha256(legacy.to_dict('records')[0]);engine=MagicMock()
    with patch('sportsbet.ingestion.snap_counts.nfl.load_snap_counts',return_value=data), \
         patch.object(pd.DataFrame,'to_sql',autospec=True) as write:
        ingest_snap_counts_seasons([2026],engine)
    frame=write.call_args.args[0];row=frame.to_dict('records')[0]
    assert row['offense_snaps']==10 and row['defense_snaps']==0
    assert row['source_record_sha256']==expected
    assert row['source_sha256']==stat_batch_sha256('nflverse','nfl',2026,[expected])
    assert row['source_observed_at'].tzinfo is not None
    assert write.call_args.kwargs['if_exists']=='append'
    assert write.call_args.args[1]=='nfl_snap_counts'
    engine.begin.assert_called_once()


def test_regular_season_scope_and_null_identity_filter_are_preserved():
    data=pl.concat([source(),source(game_type='POST',offense_snaps=-1),source(pfr_player_id=None)],how='vertical_relaxed')
    assert prepare_snap_counts(data).height==1


def test_bad_row_in_mixed_season_rejects_entire_batch_before_write():
    engine=MagicMock();data=pl.concat([source(),source(pfr_player_id='OthePl00',defense_snaps=float('nan'))])
    with patch('sportsbet.ingestion.snap_counts.nfl.load_snap_counts',return_value=data):
        with pytest.raises(ValueError,match='invalid participation'):
            ingest_snap_counts_seasons([2026],engine)
    engine.begin.assert_not_called()


def test_duplicate_participation_is_rejected_before_upsert():
    with pytest.raises(ValueError,match='duplicate participant'):
        prepare_snap_counts(pl.concat([source(),source(offense_snaps=20.0)]))


@pytest.mark.parametrize('data',[source().drop('offense_snaps'),source().head(0)])
def test_incomplete_or_empty_source_is_not_written(data):
    with pytest.raises(ValueError,match='Snap-count source'):
        prepare_snap_counts(data)
