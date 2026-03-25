"""Wave 0 test stubs for gamelog injury-join SQL patterns (SC-2).

SC-2 query builders are built in Plan 03. These stubs verify the SQL string
pattern contract before implementation begins.

All tests in this file are marked xfail(strict=False) because Plan 03 hasn't
been executed yet. When Plan 03 implements the query builders, these tests must
turn GREEN (xpass) and the xfail marks removed.

No DB connection required — pure SQL-string inspection.
"""
from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="SC-2: query builders built in Plan 03", strict=False)
def test_teammate_out_date_window_sql_pattern() -> None:
    """teammate_out filter SQL uses INTERVAL literal, never f-string injection.

    The SQL string produced for a teammate_out filter must:
      - Contain "INTERVAL" keyword (parameterized date window)
      - Use '2 days' / '1 day' window pattern for injury proximity
      - NOT contain any f-string-style {} variable injection in the SQL text

    This test will fail until Plan 03 adds the conditional query builders that
    power situational props (Phase 18 SC-2).
    """
    # Import the query builder once Plan 03 creates it.
    try:
        from sportsbet.prop.gamelog_query_builder import build_teammate_out_filter  # type: ignore[import]
    except ImportError:
        pytest.xfail("gamelog_query_builder not yet created — pending Plan 03")

    sql_fragment = build_teammate_out_filter(
        player_name="Anthony Davis",
        game_date="2024-01-15",
    )

    # Must use INTERVAL literal (not f-string date arithmetic)
    assert "INTERVAL" in sql_fragment.upper(), (
        "SQL must use INTERVAL for date window, not f-string injection"
    )

    # Must contain the 2-day look-back window
    assert "2 day" in sql_fragment.lower() or "2 days" in sql_fragment.lower(), (
        "SQL must use 2-day look-back window for teammate injury proximity"
    )

    # Must NOT contain raw f-string brace injection
    assert "{" not in sql_fragment and "}" not in sql_fragment, (
        "SQL must not contain f-string injection — use parameterized queries only"
    )


@pytest.mark.xfail(reason="SC-2: query builders built in Plan 03", strict=False)
def test_opponent_team_filter_uses_parameterized_query() -> None:
    """opponent_team filter uses $1 positional parameter, not string interpolation.

    The SQL string for opponent_team filter must:
      - Use asyncpg $N positional parameter syntax (not %s or f-string)
      - Not contain the raw team abbreviation in the SQL string text

    This test will fail until Plan 03 adds the conditional query builders.
    """
    try:
        from sportsbet.prop.gamelog_query_builder import build_opponent_filter  # type: ignore[import]
    except ImportError:
        pytest.xfail("gamelog_query_builder not yet created — pending Plan 03")

    sql_fragment, params = build_opponent_filter(opponent_team="BOS")

    # Must use asyncpg positional parameter
    assert "$" in sql_fragment, (
        "SQL must use asyncpg $N positional parameters for opponent_team filter"
    )

    # The raw team abbreviation must appear in params, not the SQL string
    assert "BOS" not in sql_fragment, (
        "Raw team abbreviation must not appear in SQL string — use positional param"
    )
    assert "BOS" in params, "opponent_team value must be in params list"
