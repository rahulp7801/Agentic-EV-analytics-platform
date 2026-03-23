"""TDD RED tests for NBAQueryBuilder and PropParams double_double extension.

These tests are written BEFORE the implementation exists (RED phase).
They define the exact contract that nba_query_builder.py must satisfy.

Security invariant tested:
- Column names come from static NBA_PROP_COLUMN_MAP (allowlist), never user input
- player_id is cast to int — nba_player_stats.player_id is INTEGER not VARCHAR
- All user values ($1, $2) are positional asyncpg params, never in the SQL string
"""
import pytest
from decimal import Decimal
from pydantic import ValidationError

# These imports will fail until Task 3 creates the module (RED phase)
from sportsbet.prop.nba_query_builder import NBAQueryBuilder, NBA_PROP_COLUMN_MAP
from sportsbet.graph.models import PropParams


def _make_nba_params(**kwargs):
    defaults = dict(
        game_id="2025_01_BOS_MIA",
        player_id="203076",
        season=2024,
        sport="nba",
        prop_type="points",
        line=Decimal("25.5"),
        filters={},
    )
    defaults.update(kwargs)
    return PropParams(**defaults)


def test_build_points_query():
    """NBAQueryBuilder.build() for 'points' returns SQL targeting nba_player_stats
    with SUM(points), $1 and $2 placeholders, and args[0] as int (not str)."""
    params = _make_nba_params(prop_type="points")
    sql, args = NBAQueryBuilder.build(params)

    assert "nba_player_stats" in sql
    assert "SUM(points)" in sql or "points" in sql.lower()
    assert "$1" in sql
    assert "$2" in sql
    assert args[0] == 203076  # int cast, not "203076" str
    assert isinstance(args[0], int)
    assert args[1] == 2024


def test_build_pra_query():
    """prop_type='pra' returns composite SQL with points + rebounds + assists,
    NOT routed through the single-column template."""
    params = _make_nba_params(prop_type="pra", line=Decimal("35.5"))
    sql, args = NBAQueryBuilder.build(params)

    # Must contain composite expression, not just a single column
    assert "points" in sql.lower()
    assert "rebounds" in sql.lower()
    assert "assists" in sql.lower()
    # Specifically should have the combined expression pattern
    assert "points + rebounds + assists" in sql.lower() or "points+rebounds+assists" in sql.lower()
    assert "$1" in sql
    assert "$2" in sql
    assert isinstance(args[0], int)


def test_build_double_double_query():
    """prop_type='double_double' returns DD template with avg_pts, avg_reb, avg_ast
    columns — NOT routed through the single-stat template."""
    params = _make_nba_params(prop_type="double_double", line=Decimal("0"))
    sql, args = NBAQueryBuilder.build(params)

    # DD template must query all three component averages
    sql_lower = sql.lower()
    assert "avg" in sql_lower
    assert "points" in sql_lower
    assert "rebounds" in sql_lower
    assert "assists" in sql_lower
    assert "nba_player_stats" in sql_lower
    assert "$1" in sql
    assert "$2" in sql
    assert isinstance(args[0], int)
    # Must NOT be the single-stat template (which has total_stat or successes pattern)
    assert "sum(case when" not in sql_lower  # NFL single-stat pattern not present


def test_unknown_prop_type_blocked():
    """PropParams with prop_type='unknown_stat' raises Pydantic ValidationError
    — Literal guard prevents open-ended column injection."""
    with pytest.raises(ValidationError):
        _make_nba_params(prop_type="unknown_stat")


def test_double_double_in_prop_params():
    """PropParams(sport='nba', prop_type='double_double') validates without error
    — proves 'double_double' is in the Literal union."""
    params = _make_nba_params(prop_type="double_double", line=Decimal("0"))
    assert params.prop_type == "double_double"
    assert params.sport == "nba"


def test_sql_injection_prevention():
    """NBA_PROP_COLUMN_MAP['points'] returns a static string 'points'.
    player_id value ('203076') must NOT appear in the SQL string template."""
    col = NBA_PROP_COLUMN_MAP["points"]
    assert col == "points"  # static string, not user input

    # Build a query and confirm player_id is never embedded in the SQL string
    params = _make_nba_params(player_id="203076", prop_type="points")
    sql, args = NBAQueryBuilder.build(params)
    assert "203076" not in sql  # player_id only in args, never in SQL


def test_player_id_cast_to_int():
    """args[0] from NBAQueryBuilder.build() is Python int for ALL NBA prop types.
    nba_player_stats.player_id is INTEGER — asyncpg requires int not str."""
    for prop_type in ("points", "rebounds", "assists", "threes", "steals", "blocks", "pra"):
        params = _make_nba_params(prop_type=prop_type, line=Decimal("10.5"))
        _, args = NBAQueryBuilder.build(params)
        assert isinstance(args[0], int), f"args[0] must be int for prop_type={prop_type!r}, got {type(args[0])}"
