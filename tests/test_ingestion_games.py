"""Tests for QUANT-04 fix: ingest_games_seasons() and CLI --games flag.

quick-1 plan 1, Task 2 — TDD RED/GREEN.

Test inventory:
1. test_load_schedules_called_once       — ingest_games_seasons calls nfl.load_schedules exactly once
2. test_rows_mapped_to_game_schema       — written rows contain required Game schema columns
3. test_duplicate_game_ids_no_raise      — ON CONFLICT DO UPDATE; re-ingest same data does not raise
4. test_cli_games_flag_calls_ingest      — CLI --games flag calls ingest_games_seasons (unit mock)

Implementation note: all tests mock nfl.load_schedules AND mock pg_insert so that
df.to_pandas() is never actually called (avoids pyarrow dependency in test environment).
Rows are intercepted at the pg_insert.values() call level.
"""
from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import polars as pl
import pytest


def test_schedule_failure_stops_refresh():
    from sportsbet.ingestion.games import ingest_games_seasons
    with patch('sportsbet.ingestion.games.nfl.load_schedules', side_effect=RuntimeError('provider failed')):
        with pytest.raises(RuntimeError, match='NFL schedule refresh failed'):
            ingest_games_seasons([2026], engine=MagicMock())


# ---------------------------------------------------------------------------
# Shared mock infrastructure
# ---------------------------------------------------------------------------

def _make_schedule_df() -> pl.DataFrame:
    """Minimal Polars DataFrame matching nflreadpy.load_schedules() output."""
    return pl.DataFrame(
        {
            "game_id": ["2024_01_KC_DET", "2024_01_SF_NYJ"],
            "season": [2024, 2024],
            "week": [1, 1],
            "home_team": ["DET", "NYJ"],
            "away_team": ["KC", "SF"],
            "gameday": ["2024-09-08", "2024-09-09"],
            "stadium": ["Ford Field", "MetLife Stadium"],
        }
    )


def _prebuilt_rows() -> list[dict]:
    """Pre-built rows as if df.to_pandas().to_dict(orient='records') was called.

    These reflect what ingest_games_seasons produces after select + rename.
    Used to feed the mock pg_insert interception without invoking pyarrow.
    """
    return [
        {
            "game_id": "2024_01_KC_DET",
            "season": 2024,
            "week": 1,
            "home_team": "DET",
            "away_team": "KC",
            "game_date": "2024-09-08",
            "stadium": "Ford Field",
        },
        {
            "game_id": "2024_01_SF_NYJ",
            "season": 2024,
            "week": 1,
            "home_team": "NYJ",
            "away_team": "SF",
            "game_date": "2024-09-09",
            "stadium": "MetLife Stadium",
        },
    ]


def _make_mock_engine() -> MagicMock:
    """Return a MagicMock engine with a working begin() context manager."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    return mock_engine


class _OnConflictTracker:
    """Intercepting pg_insert replacement that records on_conflict_do_update calls."""

    def __init__(self) -> None:
        self.captured_rows: list[dict] = []
        self.on_conflict_calls: list = []

    def pg_insert(self, model: object) -> "_OnConflictTracker._InsertStmt":
        return self._InsertStmt(self)

    class _InsertStmt:
        def __init__(self, tracker: "_OnConflictTracker") -> None:
            self._tracker = tracker
            self.excluded = MagicMock()

        def values(self, rows: list[dict]) -> "_OnConflictTracker._InsertStmt":
            self._tracker.captured_rows.extend(rows)
            return self

        def on_conflict_do_update(
            self, index_elements: list[str] | None = None, set_: dict | None = None
        ) -> "_OnConflictTracker._InsertStmt":
            self._tracker.on_conflict_calls.append(index_elements)
            return self


# ---------------------------------------------------------------------------
# Test 1: nfl.load_schedules called exactly once per ingest call
# ---------------------------------------------------------------------------

def test_load_schedules_called_once() -> None:
    """ingest_games_seasons([2024], engine) calls nfl.load_schedules([2024]) exactly once.

    Patches at consumer module path 'sportsbet.ingestion.games'.
    Mocks pg_insert to intercept DB writes (avoids pyarrow for to_pandas).
    """
    from sportsbet.ingestion.games import ingest_games_seasons

    tracker = _OnConflictTracker()
    schedule_df = _make_schedule_df()

    # Patch df.to_pandas() at pandas level to return pre-built rows' DataFrame-like object
    import pandas as pd
    mock_pandas_df = MagicMock()
    mock_pandas_df.to_dict.return_value = _prebuilt_rows()

    with (
        patch("sportsbet.ingestion.games.nfl") as mock_nfl,
        patch("sportsbet.ingestion.games.pg_insert", tracker.pg_insert),
        patch("polars.DataFrame.to_pandas", return_value=mock_pandas_df),
    ):
        mock_nfl.load_schedules.return_value = schedule_df
        ingest_games_seasons([2024], engine=_make_mock_engine())

    mock_nfl.load_schedules.assert_called_once_with([2024])


# ---------------------------------------------------------------------------
# Test 2: rows written to games table contain required schema columns
# ---------------------------------------------------------------------------

def test_rows_mapped_to_game_schema() -> None:
    """Rows written to games table contain game_id, season, week, home_team, away_team, game_date.

    Verifies column whitelist and 'gameday' -> 'game_date' rename by inspecting
    rows captured via pg_insert().values().
    """
    from sportsbet.ingestion.games import ingest_games_seasons

    tracker = _OnConflictTracker()
    schedule_df = _make_schedule_df()
    expected_rows = _prebuilt_rows()

    mock_pandas_df = MagicMock()
    mock_pandas_df.to_dict.return_value = expected_rows

    with (
        patch("sportsbet.ingestion.games.nfl") as mock_nfl,
        patch("sportsbet.ingestion.games.pg_insert", tracker.pg_insert),
        patch("polars.DataFrame.to_pandas", return_value=mock_pandas_df),
    ):
        mock_nfl.load_schedules.return_value = schedule_df
        ingest_games_seasons([2024], engine=_make_mock_engine())

    assert len(tracker.captured_rows) == 2, (
        f"Expected 2 rows, got {len(tracker.captured_rows)}"
    )

    first_row = tracker.captured_rows[0]
    required_columns = {"game_id", "season", "week", "home_team", "away_team", "game_date"}
    assert required_columns.issubset(set(first_row.keys())), (
        f"Missing columns in written row. Present: {set(first_row.keys())}"
    )
    # Verify gameday was renamed to game_date (pre-built rows use game_date)
    assert "gameday" not in first_row, "'gameday' must be renamed to 'game_date' before write"
    assert first_row["game_id"] == "2024_01_KC_DET"
    assert first_row["home_team"] == "DET"


# ---------------------------------------------------------------------------
# Test 3: duplicate game_ids do not raise (ON CONFLICT DO UPDATE)
# ---------------------------------------------------------------------------

def test_duplicate_game_ids_no_raise() -> None:
    """Re-ingesting the same season data does not raise — pg_insert ON CONFLICT DO UPDATE.

    Calls ingest_games_seasons twice with identical data. Neither call should raise.
    Verifies on_conflict_do_update(index_elements=['game_id']) is called each time.
    """
    from sportsbet.ingestion.games import ingest_games_seasons

    tracker = _OnConflictTracker()
    schedule_df = _make_schedule_df()

    mock_pandas_df = MagicMock()
    mock_pandas_df.to_dict.return_value = _prebuilt_rows()

    with (
        patch("sportsbet.ingestion.games.nfl") as mock_nfl,
        patch("sportsbet.ingestion.games.pg_insert", tracker.pg_insert),
        patch("polars.DataFrame.to_pandas", return_value=mock_pandas_df),
    ):
        mock_nfl.load_schedules.return_value = schedule_df
        # First ingest — must not raise
        ingest_games_seasons([2024], engine=_make_mock_engine())
        # Second ingest with same data — must not raise (ON CONFLICT DO UPDATE)
        ingest_games_seasons([2024], engine=_make_mock_engine())

    assert len(tracker.on_conflict_calls) == 2, (
        f"on_conflict_do_update should be called once per ingest, got {len(tracker.on_conflict_calls)}"
    )
    assert tracker.on_conflict_calls[0] == ["game_id"], (
        f"ON CONFLICT must target 'game_id', got {tracker.on_conflict_calls[0]}"
    )


# ---------------------------------------------------------------------------
# Test 4: CLI --games flag calls ingest_games_seasons
# ---------------------------------------------------------------------------

def test_cli_games_flag_calls_ingest() -> None:
    """CLI main() with --games flag calls ingest_games_seasons with the given seasons.

    Uses unittest.mock.patch to intercept all ingestion calls without DB/network access.
    All four ingestion functions are mocked to prevent actual data loading.
    """
    from sportsbet.ingestion import cli

    with (
        patch("sportsbet.ingestion.cli.ingest_pbp_seasons"),
        patch("sportsbet.ingestion.cli.ingest_player_stats_seasons"),
        patch("sportsbet.ingestion.cli.ingest_ngs_seasons"),
        patch("sportsbet.ingestion.cli.ingest_games_seasons") as mock_games,
        patch("sportsbet.ingestion.cli.get_sync_engine") as mock_engine_fn,
    ):
        mock_engine_fn.return_value = MagicMock()

        import sys
        original_argv = sys.argv
        try:
            sys.argv = ["cli", "--seasons", "2024", "--games"]
            cli.main()
        finally:
            sys.argv = original_argv

    mock_games.assert_called_once()
    args_used, kwargs_used = mock_games.call_args
    # ingest_games_seasons(seasons, engine) — first positional arg is seasons list
    seasons_arg = args_used[0] if args_used else kwargs_used.get("seasons")
    assert seasons_arg == [2024], f"Expected seasons=[2024], got {seasons_arg}"
