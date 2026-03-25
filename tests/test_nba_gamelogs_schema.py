"""Wave 0 test stubs for nba_player_gamelogs schema (SC-1).

These tests are RED until Task 2 adds the NBAPlayerGameLog ORM model and
extends PlayerStat with opponent_team / home_away columns.

No DB connection required — pure ORM introspection.
"""
from __future__ import annotations

import pytest


def test_nba_player_gamelog_orm_importable() -> None:
    """NBAPlayerGameLog must be importable from sportsbet.db.models."""
    try:
        from sportsbet.db.models import NBAPlayerGameLog  # noqa: F401
    except ImportError:
        pytest.fail(
            "NBAPlayerGameLog not found in sportsbet.db.models — add the ORM class (Task 2)"
        )
    assert hasattr(NBAPlayerGameLog, "__tablename__"), (
        "NBAPlayerGameLog must define __tablename__"
    )
    assert NBAPlayerGameLog.__tablename__ == "nba_player_gamelogs"


def test_player_stat_has_opponent_team() -> None:
    """PlayerStat must carry opponent_team and home_away nullable columns."""
    try:
        from sportsbet.db.models import PlayerStat  # noqa: F401
    except ImportError:
        pytest.fail("PlayerStat not found in sportsbet.db.models")

    assert hasattr(PlayerStat, "opponent_team"), (
        "PlayerStat is missing opponent_team column — add in Task 2"
    )
    assert hasattr(PlayerStat, "home_away"), (
        "PlayerStat is missing home_away column — add in Task 2"
    )


def test_nba_player_gamelog_has_required_columns() -> None:
    """NBAPlayerGameLog must expose all per-game columns needed by Phase 18 queries."""
    try:
        from sportsbet.db.models import NBAPlayerGameLog
    except ImportError:
        pytest.skip("NBAPlayerGameLog not yet defined — pending Task 2")

    required = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "game_id",
        "game_date",
        "season",
        "is_home",
        "opponent_team",
        "minutes",
        "points",
        "rebounds",
        "assists",
        "threes_made",
        "steals",
        "blocks",
    ]
    for col in required:
        assert hasattr(NBAPlayerGameLog, col), (
            f"NBAPlayerGameLog missing column: {col}"
        )
