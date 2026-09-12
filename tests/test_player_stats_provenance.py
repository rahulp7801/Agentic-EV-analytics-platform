from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import polars as pl

from sportsbet.ingestion.player_stats import ingest_player_stats_seasons
from sportsbet.ingestion.provenance import stat_row_sha256


def test_nfl_ingestion_attaches_reproducible_source_and_record_evidence():
    data=pl.DataFrame([dict(player_id='gsis-1',player_display_name='Player',recent_team='BUF',
        season=2026,week=1,season_type='REG',passing_yards=251,rushing_yards=3,
        receiving_yards=0)])
    captured=[]
    def capture(frame,name,*args,**kwargs):
        captured.append(frame.copy())
    engine=MagicMock()
    with patch('sportsbet.ingestion.player_stats.nfl.load_player_stats',return_value=data), \
         patch.object(pd.DataFrame,'to_sql',capture):
        ingest_player_stats_seasons([2026],engine)
    frame,=captured;row=frame.iloc[0].to_dict()
    assert row['source_provider']=='nflverse'
    assert len(row['source_sha256'])==64
    assert row['source_record_sha256']==stat_row_sha256('nfl',row)
    observed=row['source_observed_at']
    assert isinstance(observed,datetime) and observed.tzinfo is not None and observed.utcoffset() is not None
