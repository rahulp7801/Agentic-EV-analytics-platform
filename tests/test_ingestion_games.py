"""Tests for QUANT-04 fix: ingest_games_seasons() and CLI --games flag.

quick-1 plan 1, Task 2 — TDD RED/GREEN.

Test inventory:
1. test_load_schedules_called_once       — ingest_games_seasons calls nfl.load_schedules exactly once
2. test_rows_mapped_to_game_schema       — written rows contain required Game schema columns
3. test_duplicate_game_ids_no_raise      — ON CONFLICT DO NOTHING; re-ingest same data does not raise
4. test_cli_games_flag_calls_ingest      — CLI --games flag calls ingest_games_seasons (unit mock)
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import polars as pl
import pytest


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Test 1: nfl.load_schedules called exactly once per ingest call
# ---------------------------------------------------------------------------

def test_load_schedules_called_once() -> None:
    """ingest_games_seasons([2024], engine) calls nfl.load_schedules([2024]) exactly once.

    Patches at consumer module path 'sportsbet.ingestion.games' per Phase 8 pattern.
    Uses mock engine to avoid DB dependency.
    """
    from sportsbet.ingestion.games import ingest_games_seasons

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    schedule_df = _make_schedule_df()

    with patch("sportsbet.ingestion.games.nfl") as mock_nfl:
        mock_nfl.load_schedules.return_value = schedule_df
        ingest_games_seasons([2024], engine=mock_engine)

    mock_nfl.load_schedules.assert_called_once_with([2024])


# ---------------------------------------------------------------------------
# Test 2: rows written to games table contain required schema columns
# ---------------------------------------------------------------------------

def test_rows_mapped_to_game_schema() -> None:
    """Rows written to games table contain game_id, season, week, home_team, away_team, game_date.

    Verifies column whitelist and 'gameday' -> 'game_date' rename.
    Inspects the rows dict passed to pg_insert().values().
    """
    from sportsbet.ingestion.games import ingest_games_seasons

    mock_engine = MagicMock()
    written_rows: list[list[dict]] = []

    class _FakeConn:
        def execute(self, stmt: object) -> None:
            pass

    class _FakeCM:
        def __enter__(self) -> _FakeConn:
            return _FakeConn()

        def __exit__(self, *args: object) -> bool:
            return False

    mock_engine.begin.return_value = _FakeCM()

    schedule_df = _make_schedule_df()

    captured_values: list = []

    def _fake_pg_insert(model: object) -> MagicMock:
        mock_insert = MagicMock()

        def _values(rows: list[dict]) -> MagicMock:
            captured_values.extend(rows)
            mock_stmt = MagicMock()
            mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
            return mock_stmt

        mock_insert.values = _values
        return mock_insert

    with (
        patch("sportsbet.ingestion.games.nfl") as mock_nfl,
        patch("sportsbet.ingestion.games.pg_insert", _fake_pg_insert),
    ):
        mock_nfl.load_schedules.return_value = schedule_df
        ingest_games_seasons([2024], engine=mock_engine)

    assert len(captured_values) == 2, f"Expected 2 rows, got {len(captured_values)}"

    first_row = captured_values[0]
    required_columns = {"game_id", "season", "week", "home_team", "away_team", "game_date"}
    assert required_columns.issubset(set(first_row.keys())), (
        f"Missing columns in written row. Present: {set(first_row.keys())}"
    )
    # Verify gameday was renamed to game_date
    assert "gameday" not in first_row, "'gameday' must be renamed to 'game_date' before write"
    assert first_row["game_id"] == "2024_01_KC_DET"
    assert first_row["home_team"] == "DET"


# ---------------------------------------------------------------------------
# Test 3: duplicate game_ids do not raise (ON CONFLICT DO NOTHING)
# ---------------------------------------------------------------------------

def test_duplicate_game_ids_no_raise() -> None:
    """Re-ingesting the same season data does not raise — pg_insert ON CONFLICT DO NOTHING.

    Calls ingest_games_seasons twice with identical data. Neither call should raise.
    The pg_insert mock verifies on_conflict_do_nothing(index_elements=['game_id']) is used.
    """
    from sportsbet.ingestion.games import ingest_games_seasons

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    schedule_df = _make_schedule_df()

    on_conflict_calls: list = []

    class _MockInsertStmt:
        def values(self, rows: list[dict]) -> "_MockInsertStmt":
            return self

        def on_conflict_do_nothing(self, index_elements: list[str] | None = None) -> "_MockInsertStmt":
            on_conflict_calls.append(index_elements)
            return self

    def _fake_pg_insert(model: object) -> _MockInsertStmt:
        return _MockInsertStmt()

    with (
        patch("sportsbet.ingestion.games.nfl") as mock_nfl,
        patch("sportsbet.ingestion.games.pg_insert", _fake_pg_insert),
    ):
        mock_nfl.load_schedules.return_value = schedule_df
        # First ingest — should not raise
        ingest_games_seasons([2024], engine=mock_engine)
        # Second ingest with same data — should not raise (ON CONFLICT DO NOTHING)
        ingest_games_seasons([2024], engine=mock_engine)

    assert len(on_conflict_calls) == 2, (
        f"on_conflict_do_nothing should be called once per ingest, got {len(on_conflict_calls)}"
    )
    # Verify conflict resolution targets game_id primary key
    assert on_conflict_calls[0] == ["game_id"], (
        f"ON CONFLICT must target 'game_id', got {on_conflict_calls[0]}"
    )


# ---------------------------------------------------------------------------
# Test 4: CLI --games flag calls ingest_games_seasons
# ---------------------------------------------------------------------------

def test_cli_games_flag_calls_ingest() -> None:
    """CLI main() with --games flag calls ingest_games_seasons with the given seasons.

    Uses unittest.mock.patch to intercept the call without DB access.
    """
    from sportsbet.ingestion import cli

    with (
        patch("sportsbet.ingestion.cli.ingest_pbp_seasons") as mock_pbp,
        patch("sportsbet.ingestion.cli.ingest_games_seasons") as mock_games,
        patch("sportsbet.ingestion.cli.get_sync_engine") as mock_engine_fn,
    ):
        mock_engine = MagicMock()
        mock_engine_fn.return_value = mock_engine

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
