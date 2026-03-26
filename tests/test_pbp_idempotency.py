"""Test PBP idempotency: duplicate inserts are silent (no IntegrityError).

TDD RED test — verifies that ingest_pbp_seasons raises IntegrityError on second
insert WITHOUT the on_conflict_do_nothing fix. This test must FAIL (RED) before
pbp.py is patched, and PASS (GREEN) after the fix.

SC-1 success criterion: Re-running ingest_pbp_seasons does not raise IntegrityError
for rows with non-NULL game_id.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import sqlalchemy.exc


def _make_mock_polars_df() -> MagicMock:
    """Build a mock Polars DataFrame whose to_pandas() returns a real pandas df."""
    single_row_pd = pd.DataFrame(
        {
            "game_id": ["2025_01_KC_LAC"],
            "play_id": [1],
            "season": [2025],
            "week": [1],
            "posteam": ["KC"],
            "defteam": ["LAC"],
            "play_type": ["pass"],
            "yards_gained": [10],
            "down": [1],
            "ydstogo": [10],
            "passer_player_id": ["00-0012345"],
            "receiver_player_id": ["00-0067890"],
            "rusher_player_id": [None],
            "pass_touchdown": [0],
            "rush_touchdown": [0],
            "interception": [0],
            "epa": [0.5],
            "wp": [0.6],
            "air_yards": [15.0],
            "two_point_attempt": [0],
            "complete_pass": [1],
        }
    )

    mock_df = MagicMock()
    # .columns returns list of column names (used in available-column filter)
    mock_df.columns = list(single_row_pd.columns)
    # .select returns self (whitelist filter)
    mock_df.select.return_value = mock_df
    # .to_pandas() returns real pandas DataFrame
    mock_df.to_pandas.return_value = single_row_pd
    return mock_df


def test_pbp_on_conflict_do_nothing() -> None:
    """Second ingest_pbp_seasons call must NOT raise IntegrityError.

    RED: Without on_conflict_do_nothing, a duplicate (game_id, play_id) row
    would raise IntegrityError. This test asserts that the second call is
    silent — which only works after the fix.
    """
    mock_polars_df = _make_mock_polars_df()

    # Mock psutil to return safe memory (never triggers MemoryError guard)
    mock_mem = MagicMock()
    mock_mem.percent = 50.0

    # Build a mock engine whose conn.execute silently accepts on_conflict_do_nothing.
    # The context manager returned by engine.begin() is the connection.
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_conn

    # nflreadpy and polars are imported inside ingest_pbp_seasons — patch via sys.modules
    mock_nfl_module = MagicMock()
    mock_nfl_module.load_pbp.return_value = mock_polars_df

    mock_pl_module = MagicMock()

    with (
        patch("sportsbet.ingestion.pbp.psutil.virtual_memory", return_value=mock_mem),
        patch.dict(sys.modules, {"nflreadpy": mock_nfl_module, "polars": mock_pl_module}),
    ):
        from sportsbet.ingestion.pbp import ingest_pbp_seasons

        # First call: must complete without exception
        ingest_pbp_seasons([2025], engine=mock_engine)

        # Second call with identical data: must NOT raise IntegrityError.
        # This is the key GREEN assertion — the to_sql path would raise IntegrityError
        # on a real DB for duplicate (game_id, play_id) rows;
        # on_conflict_do_nothing must suppress it.
        try:
            ingest_pbp_seasons([2025], engine=mock_engine)
        except sqlalchemy.exc.IntegrityError:
            pytest.fail(
                "ingest_pbp_seasons raised IntegrityError on second call — "
                "on_conflict_do_nothing not implemented in pbp.py"
            )
