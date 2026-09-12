from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from sportsbet.ingestion.provenance import stat_batch_sha256, stat_row_sha256


def nba_row(**changes):
    return dict(player_id=np.int64(7),game_id='game',game_date=date(2026,1,2),
        team_abbreviation='BOS',points=np.float64(21),rebounds=None,assists=float('nan')) | changes


def test_stat_record_hash_normalizes_stored_integer_and_null_types():
    expected=stat_row_sha256('nba',nba_row())
    equivalent=nba_row(player_id=7,game_date='2026-01-02',points=Decimal('21.0'),assists=None)
    assert stat_row_sha256('nba',equivalent)==expected
    assert stat_row_sha256('nba',nba_row(points=22))!=expected


@pytest.mark.parametrize('change',[{'points':21.5},{'points':float('inf')},{'team_abbreviation':''}])
def test_stat_record_hash_rejects_values_storage_cannot_trust(change):
    with pytest.raises(ValueError):
        stat_row_sha256('nba',nba_row(**change))


def test_batch_hash_is_order_independent_and_binds_scope():
    records=[stat_row_sha256('nba',nba_row()),stat_row_sha256('nba',nba_row(player_id=8))]
    expected=stat_batch_sha256('nba','nba',2025,records)
    assert stat_batch_sha256('nba','nba',2025,list(reversed(records)))==expected
    assert stat_batch_sha256('nba','nba',2026,records)!=expected
    with pytest.raises(ValueError):
        stat_batch_sha256('nflverse','nba',2025,records)
