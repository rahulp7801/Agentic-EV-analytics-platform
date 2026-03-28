"""Wave 0 test stubs for SC-4: PropQueryBuilder and NBAQueryBuilder situational filters.

SC-4 query builder extensions are implemented in Plan 03 (Phase 18 Task 2 and 3).
Tests that require builder changes are expected to fail (RED) until Tasks 2-3 implement
the situational WHERE clause construction.

No DB connection required — pure SQL-string inspection.
Security invariant checked: user data in args tuple, never in SQL string.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from sportsbet.graph.models import PropParams


def _nfl_params(**kwargs: object) -> PropParams:
    """Convenience: build a minimal valid NFL PropParams with overrides."""
    defaults: dict[str, object] = {
        "game_id": "g1",
        "player_id": "P1",
        "season": 2023,
        "sport": "nfl",
        "prop_type": "pass_yds",
        "line": Decimal("250.5"),
        "filters": {},
    }
    defaults.update(kwargs)
    return PropParams(**defaults)  # type: ignore[arg-type]


def _nba_params(**kwargs: object) -> PropParams:
    """Convenience: build a minimal valid NBA PropParams with overrides."""
    defaults: dict[str, object] = {
        "game_id": "g1",
        "player_id": "1628384",
        "season": 2023,
        "sport": "nba",
        "prop_type": "points",
        "line": Decimal("25.5"),
        "filters": {},
    }
    defaults.update(kwargs)
    return PropParams(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# NFL situational filter tests (Task 2 turns these GREEN)
# ---------------------------------------------------------------------------


def test_nfl_opponent_team_filter_uses_positional_param() -> None:
    """opponent_team filter appends 'AND opponent_team = $N' — value in args, not SQL."""
    from sportsbet.prop.query_builder import PropQueryBuilder

    params = _nfl_params(opponent_team="BOS")
    sql, args = PropQueryBuilder.build(params)

    # Must use positional $N placeholder — never f-string interpolation
    assert "opponent_team" in sql, "SQL must reference opponent_team column"
    assert "$" in sql, "SQL must use positional $N params"
    # User-supplied value must be in args, NOT embedded in SQL string
    assert "BOS" not in sql, "Raw opponent_team value must not appear in SQL string"
    assert "BOS" in args, "opponent_team value must be in args tuple"


def test_nfl_home_away_filter_uses_positional_param() -> None:
    """home_away filter appends 'AND home_away = $N' — string value in args."""
    from sportsbet.prop.query_builder import PropQueryBuilder

    params = _nfl_params(home_away="home")
    sql, args = PropQueryBuilder.build(params)

    assert "home_away" in sql, "SQL must reference home_away column"
    assert "$" in sql, "SQL must use positional $N params"
    # "home" string must be in args, not embedded directly in SQL
    assert "home" in args, "home_away value must be in args tuple"


def test_nfl_last_n_games_subquery_uses_limit() -> None:
    """last_n_games filter appends a subquery with LIMIT $N — no ORDER BY magic string injection."""
    from sportsbet.prop.query_builder import PropQueryBuilder

    params = _nfl_params(last_n_games=10)
    sql, args = PropQueryBuilder.build(params)

    assert "LIMIT" in sql.upper(), "SQL must contain LIMIT for last_n_games subquery"
    assert "$" in sql, "SQL must use positional $N params"
    # The integer value 10 must be in args, not raw in SQL
    assert 10 in args, "last_n_games integer value must be in args tuple"


def test_teammate_out_uses_date_window_not_game_id_join() -> None:
    """teammate_out filter uses INTERVAL date-window join, NOT game_id equality join.

    This test also validates the SC-2 requirement: INTERVAL keyword must appear.
    When this turns GREEN it promotes the xfail in test_gamelog_injury_join.py.
    """
    from sportsbet.prop.query_builder import PropQueryBuilder

    params = _nfl_params(teammate_out=["1628384"])
    sql, args = PropQueryBuilder.build(params)

    # Must use INTERVAL for date-window approximation (injury_reports.game_id is nullable)
    assert "INTERVAL" in sql.upper(), (
        "SQL must use INTERVAL date window for teammate_out — not direct game_id join"
    )
    assert "$" in sql, "SQL must use positional $N params for teammate name"
    # Teammate player ID must appear in args, not in SQL string
    assert "1628384" not in sql, "Teammate player ID must not appear in SQL string"
    assert "1628384" in args, "Teammate player ID must be in args tuple"


def test_no_situational_fields_unchanged_sql() -> None:
    """No situational fields set → SQL identical to current baseline (regression test)."""
    from sportsbet.prop.query_builder import PropQueryBuilder

    # Baseline: params with no situational fields
    params_baseline = _nfl_params()
    sql_baseline, args_baseline = PropQueryBuilder.build(params_baseline)

    # With explicit None fields — should be identical
    params_none = _nfl_params(
        opponent_team=None,
        home_away=None,
        last_n_games=None,
        teammate_out=None,
    )
    sql_none, args_none = PropQueryBuilder.build(params_none)

    assert sql_none == sql_baseline, (
        "SQL must be identical when all situational fields are None (regression)"
    )
    assert args_none == args_baseline, (
        "Args must be identical when all situational fields are None (regression)"
    )


# ---------------------------------------------------------------------------
# NBA situational filter tests (Task 3 turns these GREEN)
# ---------------------------------------------------------------------------


def test_nba_gamelog_template_used_when_conditional() -> None:
    """NBAQueryBuilder dispatches to nba_player_gamelogs when opponent_team is set."""
    from sportsbet.prop.nba_query_builder import NBAQueryBuilder

    params = _nba_params(opponent_team="GSW")
    sql, args = NBAQueryBuilder.build(params)

    # Must reference nba_player_gamelogs, not nba_player_stats
    assert "nba_player_gamelogs" in sql, (
        "Conditional NBA query must use nba_player_gamelogs template, not nba_player_stats"
    )


def test_nba_opponent_filter_uses_positional_param() -> None:
    """NBA opponent_team filter appends 'AND opponent_team = $N' — value in args."""
    from sportsbet.prop.nba_query_builder import NBAQueryBuilder

    params = _nba_params(opponent_team="GSW")
    sql, args = NBAQueryBuilder.build(params)

    assert "opponent_team" in sql, "SQL must reference opponent_team column"
    assert "$" in sql, "SQL must use positional $N params"
    # User-supplied value must be in args, NOT embedded in SQL string
    assert "GSW" not in sql, "Raw opponent_team value must not appear in SQL string"
    assert "GSW" in args, "opponent_team value must be in args tuple"


def test_teammate_out_contexts_uses_player_stats_absence() -> None:
    """teammate_out_contexts uses player_stats NOT EXISTS, not injury_reports INTERVAL.

    When teammate_out_contexts is set (team+position context available), PropQueryBuilder
    should use player_stats absence detection — works for historical data.
    """
    from sportsbet.prop.query_builder import PropQueryBuilder

    params = _nfl_params(
        teammate_out_contexts=[{"name": "Patrick Mahomes", "team": "KC", "position": "QB"}]
    )
    sql, args = PropQueryBuilder.build(params)

    # Must use player_stats absence (NOT EXISTS), not injury_reports INTERVAL
    assert "NOT EXISTS" in sql.upper(), "teammate_out_contexts must use NOT EXISTS subquery"
    assert "player_stats" in sql, "teammate_out_contexts must reference player_stats table"
    assert "INTERVAL" not in sql.upper() or "NOT EXISTS" in sql.upper(), (
        "teammate_out_contexts path must use player_stats absence, not INTERVAL only"
    )
    # Team and position must be in args, NOT embedded in SQL string
    assert "KC" not in sql, "Raw team abbreviation must not appear in SQL string"
    assert "QB" not in sql, "Raw position must not appear in SQL string"
    assert "KC" in args, "Team must be in args tuple"
    assert "QB" in args, "Position must be in args tuple"


def test_teammate_out_contexts_skips_unknown_position() -> None:
    """teammate_out_contexts with Unknown position is skipped — no filter appended."""
    from sportsbet.prop.query_builder import PropQueryBuilder

    params = _nfl_params(
        teammate_out_contexts=[{"name": "John Doe", "team": "KC", "position": "Unknown"}]
    )
    sql, args = PropQueryBuilder.build(params)

    # Unknown position should be skipped — no extra WHERE clause added
    assert "NOT EXISTS" not in sql.upper(), (
        "Unknown position entry in teammate_out_contexts must be skipped"
    )


def test_nba_teammate_out_uses_gamelog_absence() -> None:
    """NBA teammate_out filter uses nba_player_gamelogs NOT EXISTS, not INTERVAL."""
    from sportsbet.prop.nba_query_builder import NBAQueryBuilder

    params = _nba_params(
        opponent_team="GSW",  # ensures conditional path
        teammate_out=["Anthony Davis"],
    )
    sql, args = NBAQueryBuilder.build(params)

    assert "NOT EXISTS" in sql.upper(), "NBA teammate_out must use NOT EXISTS"
    assert "nba_player_gamelogs" in sql, "NBA teammate_out must reference nba_player_gamelogs"
    assert "Anthony Davis" not in sql, "Player name must not appear in SQL string"
    assert "Anthony Davis" in args, "Player name must be in args tuple"


def test_prop_params_accepts_teammate_out_contexts() -> None:
    """PropParams accepts teammate_out_contexts as list of dicts."""
    params = _nfl_params(
        teammate_out_contexts=[{"name": "Patrick Mahomes", "team": "KC", "position": "QB"}]
    )
    assert params.teammate_out_contexts == [{"name": "Patrick Mahomes", "team": "KC", "position": "QB"}]


def test_prop_params_teammate_out_contexts_defaults_none() -> None:
    """teammate_out_contexts defaults to None (backward compatible)."""
    params = _nfl_params()
    assert params.teammate_out_contexts is None
