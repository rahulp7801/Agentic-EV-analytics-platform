"""Wave 0 test stubs for nba_gamelogs ingest pipeline (SC-1).

These tests are RED until Task 3 creates src/sportsbet/ingestion/nba_gamelogs.py.

Uses unittest.mock.patch to intercept PlayerGameLogs — the import site is
sportsbet.ingestion.nba_gamelogs.PlayerGameLogs (Phase 8 locked decision:
module-level imports are patchable, closure-scoped imports are not).

No DB connection required — engine is a MagicMock.
"""
from __future__ import annotations

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

# Skip entire module cleanly until Task 3 creates the module.
nba_gamelogs = pytest.importorskip(
    "sportsbet.ingestion.nba_gamelogs",
    reason="nba_gamelogs module not yet created — pending Task 3",
)


# ---------------------------------------------------------------------------
# Matchup parsing unit tests (pure Python — no mock needed)
# ---------------------------------------------------------------------------


def test_matchup_parsing_home() -> None:
    """MATCHUP 'LAL vs. GSW' => is_home=True, opponent_team='GSW'."""
    import re

    matchup = "LAL vs. GSW"
    is_home = "@" not in matchup
    opponent_team = re.split(r" @ | vs\. ", matchup)[-1].strip()

    assert is_home is True
    assert opponent_team == "GSW"


def test_matchup_parsing_away() -> None:
    """MATCHUP 'LAL @ BOS' => is_home=False, opponent_team='BOS'."""
    import re

    matchup = "LAL @ BOS"
    is_home = "@" not in matchup
    opponent_team = re.split(r" @ | vs\. ", matchup)[-1].strip()

    assert is_home is False
    assert opponent_team == "BOS"


def test_matchup_parsing_whitespace() -> None:
    """Extra whitespace in MATCHUP is stripped: 'LAL  @  BOS' => opponent_team='BOS'."""
    import re

    matchup = "LAL  @  BOS"
    opponent_team = re.split(r" @ | vs\. ", matchup.strip())[-1].strip()
    assert opponent_team == "BOS"


# ---------------------------------------------------------------------------
# Integration stub: ingest_nba_gamelogs_season with mocked PlayerGameLogs
# ---------------------------------------------------------------------------


def _make_sample_df() -> pd.DataFrame:
    """Return a 3-row sample DataFrame matching NBA API PlayerGameLogs shape."""
    return pd.DataFrame(
        {
            "PLAYER_ID": [2544, 2544, 2544],
            "PLAYER_NAME": ["LeBron James", "LeBron James", "LeBron James"],
            "TEAM_ABBREVIATION": ["LAL", "LAL", "LAL"],
            "GAME_ID": ["0022300001", "0022300002", "0022300003"],
            "GAME_DATE": ["2023-10-24", "2023-10-26", "2023-10-28"],
            "MATCHUP": ["LAL vs. DEN", "LAL @ GSW", "LAL vs. PHX"],
            "MIN": [35.0, 32.0, 38.0],
            "PTS": [28, 25, 31],
            "REB": [7, 8, 9],
            "AST": [8, 7, 10],
            "FG3M": [2, 1, 3],
            "STL": [1, 2, 0],
            "BLK": [0, 1, 1],
        }
    )


def test_ingest_nba_gamelogs_season_mock() -> None:
    """ingest_nba_gamelogs_season() calls to_sql('nba_player_gamelogs', ...) with correct data."""
    from sportsbet.ingestion.nba_gamelogs import ingest_nba_gamelogs_season

    mock_engine = MagicMock()
    sample_df = _make_sample_df()

    mock_logs_instance = MagicMock()
    mock_logs_instance.get_data_frames.return_value = [sample_df]

    with (
        patch(
            "sportsbet.ingestion.nba_gamelogs.PlayerGameLogs",
            return_value=mock_logs_instance,
        ) as mock_cls,
        patch("sportsbet.ingestion.nba_gamelogs.time") as mock_time,
        patch("sportsbet.ingestion.nba_gamelogs.pd") as mock_pd,
    ):
        # We need real pandas for DataFrame ops — only mock to_sql call
        # Re-approach: patch to_sql at the DataFrame level instead.
        pass

    # Simpler approach: patch time.sleep and let real pandas run, mock engine.
    with (
        patch(
            "sportsbet.ingestion.nba_gamelogs.PlayerGameLogs",
            return_value=mock_logs_instance,
        ),
        patch("sportsbet.ingestion.nba_gamelogs.time") as mock_time,
    ):
        # Capture to_sql calls by monkey-patching DataFrame.to_sql
        to_sql_calls: list = []

        original_to_sql = pd.DataFrame.to_sql

        def capture_to_sql(self: pd.DataFrame, name: str, *args, **kwargs) -> None:  # type: ignore[override]
            to_sql_calls.append({"name": name, "df": self.copy()})

        pd.DataFrame.to_sql = capture_to_sql  # type: ignore[method-assign]
        try:
            ingest_nba_gamelogs_season(2023, mock_engine)
        finally:
            pd.DataFrame.to_sql = original_to_sql  # type: ignore[method-assign]

    # Verify to_sql called with correct table name
    assert len(to_sql_calls) == 1, f"Expected 1 to_sql call, got {len(to_sql_calls)}"
    call = to_sql_calls[0]
    assert call["name"] == "nba_player_gamelogs"

    result_df: pd.DataFrame = call["df"]

    # Verify is_home derived correctly from MATCHUP
    assert "is_home" in result_df.columns, "is_home column missing from output DataFrame"
    assert result_df.iloc[0]["is_home"] is True or result_df.iloc[0]["is_home"] == True  # LAL vs. DEN  # noqa: E712
    assert result_df.iloc[1]["is_home"] is False or result_df.iloc[1]["is_home"] == False  # LAL @ GSW  # noqa: E712

    # Verify opponent_team derived correctly
    assert "opponent_team" in result_df.columns, "opponent_team column missing"
    assert result_df.iloc[0]["opponent_team"] == "DEN"
    assert result_df.iloc[1]["opponent_team"] == "GSW"

    # Verify MATCHUP column was dropped
    assert "MATCHUP" not in result_df.columns, "MATCHUP raw column must be dropped"

    from sportsbet.ingestion.provenance import stat_row_sha256
    assert set(result_df['source_provider'])=={'nba'}
    assert result_df['source_sha256'].str.fullmatch('[0-9a-f]{64}').all()
    assert result_df['source_sha256'].nunique()==1
    assert all(row['source_record_sha256']==stat_row_sha256('nba',row)
        for row in result_df.to_dict('records'))
    assert all(value.tzinfo is not None and value.utcoffset() is not None
        for value in result_df['source_observed_at'])

    # Verify mandatory rate limit sleep was called
    mock_time.sleep.assert_called_once_with(1)
