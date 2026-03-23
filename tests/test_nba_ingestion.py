"""Unit tests for NBA player stats ingestion (NBA-01).

Tests cover:
- Season string format conversion (int year -> "YYYY-YY" format)
- Column whitelist filtering (only NBA_COLUMNS passed to to_sql)
- gc.collect() called once per season
- time.sleep(1) called once per season
- ReadTimeout handled per-season with skip + continue

All tests mock nba_api to avoid real HTTP calls.
"""
from __future__ import annotations

import gc
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

from sportsbet.ingestion.nba import ingest_nba_seasons, NBA_COLUMNS


def _make_fake_df() -> pd.DataFrame:
    """Return a small DataFrame with all NBA_COLUMNS + extra columns (to test filtering)."""
    data = {col: [1, 2] for col in NBA_COLUMNS}
    # Add extra columns that should be filtered out
    data["EXTRA_COL"] = ["x", "y"]
    data["ANOTHER_EXTRA"] = [True, False]
    return pd.DataFrame(data)


def _mock_stats_cls(fake_df: pd.DataFrame) -> MagicMock:
    """Build a MagicMock for LeagueDashPlayerStats that returns fake_df."""
    mock_stats_instance = MagicMock()
    mock_stats_instance.get_data_frames.return_value = [fake_df]
    mock_cls = MagicMock(return_value=mock_stats_instance)
    return mock_cls


def _make_mock_engine() -> MagicMock:
    """Return a MagicMock SQLAlchemy engine."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Test 1: season string format
# ---------------------------------------------------------------------------

def test_nba_season_format() -> None:
    """ingest_nba_seasons must format season int as 'YYYY-YY' for LeagueDashPlayerStats.

    - 2022 -> "2022-23"
    - 2009 -> "2009-10"  (edge case: str(2010)[-2:] == "10", not "10")
    """
    fake_df = _make_fake_df()
    mock_cls = _mock_stats_cls(fake_df)
    engine = _make_mock_engine()

    with patch("sportsbet.ingestion.nba.LeagueDashPlayerStats", mock_cls):
        with patch("time.sleep"):
            ingest_nba_seasons([2022, 2009], engine=engine)

    calls = mock_cls.call_args_list
    assert len(calls) == 2, f"Expected 2 LeagueDashPlayerStats calls, got {len(calls)}"

    # Check 2022 -> "2022-23"
    assert calls[0].kwargs["season"] == "2022-23", (
        f"Expected '2022-23', got '{calls[0].kwargs['season']}'"
    )
    # Check 2009 -> "2009-10" (edge case)
    assert calls[1].kwargs["season"] == "2009-10", (
        f"Expected '2009-10', got '{calls[1].kwargs['season']}'"
    )


# ---------------------------------------------------------------------------
# Test 2: column whitelist
# ---------------------------------------------------------------------------

def test_nba_column_whitelist() -> None:
    """Only NBA_COLUMNS columns (plus 'season') must be passed to df.to_sql.

    Extra columns returned by nba_api should be dropped before writing.
    """
    fake_df = _make_fake_df()  # includes EXTRA_COL, ANOTHER_EXTRA
    mock_cls = _mock_stats_cls(fake_df)
    engine = _make_mock_engine()

    captured_dfs: list[pd.DataFrame] = []

    # Intercept to_sql calls by patching pd.DataFrame.to_sql
    original_to_sql = pd.DataFrame.to_sql

    def capturing_to_sql(self: pd.DataFrame, name: str, *args, **kwargs) -> None:  # type: ignore[override]
        if name == "nba_player_stats":
            captured_dfs.append(self.copy())

    with patch("sportsbet.ingestion.nba.LeagueDashPlayerStats", mock_cls):
        with patch("time.sleep"):
            with patch.object(pd.DataFrame, "to_sql", capturing_to_sql):
                ingest_nba_seasons([2022], engine=engine)

    assert len(captured_dfs) == 1, "Expected exactly 1 to_sql call for nba_player_stats"
    written_df = captured_dfs[0]

    # "season" column is added by ingestion code — all others must be from rename map
    expected_columns = set(
        [
            "player_id", "player_name", "team_id", "team_abbreviation",
            "games_played", "minutes", "points", "rebounds", "assists",
            "threes_made", "steals", "blocks",
            "season",  # added by ingest_nba_seasons
        ]
    )
    actual_columns = set(written_df.columns)

    # Extra nba_api columns must NOT be present
    assert "EXTRA_COL" not in actual_columns, "EXTRA_COL was not filtered out"
    assert "ANOTHER_EXTRA" not in actual_columns, "ANOTHER_EXTRA was not filtered out"

    # All expected renamed columns must be present
    for col in expected_columns:
        assert col in actual_columns, f"Expected column '{col}' missing from written DataFrame"


# ---------------------------------------------------------------------------
# Test 3: gc.collect() called once per season
# ---------------------------------------------------------------------------

def test_nba_gc_collect() -> None:
    """gc.collect() must be called exactly once per season in the ingestion loop."""
    fake_df = _make_fake_df()
    mock_cls = _mock_stats_cls(fake_df)
    engine = _make_mock_engine()

    with patch("sportsbet.ingestion.nba.LeagueDashPlayerStats", mock_cls):
        with patch("time.sleep"):
            with patch("gc.collect") as mock_gc:
                ingest_nba_seasons([2022, 2023], engine=engine)

    # gc.collect called once per season = 2 times total
    assert mock_gc.call_count == 2, (
        f"Expected gc.collect() called 2 times (once per season), got {mock_gc.call_count}"
    )


# ---------------------------------------------------------------------------
# Test 4: time.sleep(1) called once per season
# ---------------------------------------------------------------------------

def test_nba_sleep() -> None:
    """time.sleep(1) must be called exactly once per season (NBA.com rate limit)."""
    fake_df = _make_fake_df()
    mock_cls = _mock_stats_cls(fake_df)
    engine = _make_mock_engine()

    with patch("sportsbet.ingestion.nba.LeagueDashPlayerStats", mock_cls):
        with patch("time.sleep") as mock_sleep:
            ingest_nba_seasons([2022, 2023], engine=engine)

    # time.sleep(1) called once per season = 2 times total
    assert mock_sleep.call_count == 2, (
        f"Expected time.sleep called 2 times (once per season), got {mock_sleep.call_count}"
    )
    # Each call must pass 1 second
    for c in mock_sleep.call_args_list:
        assert c == call(1), f"Expected time.sleep(1), got time.sleep({c})"


# ---------------------------------------------------------------------------
# Test 5: ReadTimeout causes season skip (loop continues)
# ---------------------------------------------------------------------------

def test_nba_timeout_skip() -> None:
    """If LeagueDashPlayerStats raises an Exception for one season, that season is skipped.

    The loop must continue to the next season without re-raising the exception.
    Uses a generic Exception (matching requests.exceptions.ReadTimeout behavior).
    """
    fake_df = _make_fake_df()
    engine = _make_mock_engine()

    # Season 2022 raises ReadTimeout; season 2023 succeeds
    call_count = [0]

    def side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("ReadTimeout: HTTPSConnectionPool")
        mock_instance = MagicMock()
        mock_instance.get_data_frames.return_value = [fake_df]
        return mock_instance

    with patch("sportsbet.ingestion.nba.LeagueDashPlayerStats", side_effect=side_effect):
        with patch("time.sleep"):
            with patch("gc.collect"):
                # Must NOT raise — should complete silently skipping 2022
                ingest_nba_seasons([2022, 2023], engine=engine)

    # Both seasons were attempted (call_count == 2)
    assert call_count[0] == 2, (
        f"Expected 2 LeagueDashPlayerStats calls (both seasons attempted), got {call_count[0]}"
    )
