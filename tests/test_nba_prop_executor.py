"""TDD RED tests for run_nba_prop_query executor — NormalDist probability model.

These tests are written BEFORE the implementation exists (RED phase).
They define the exact contract that nba_executor.py must satisfy.

Key invariants tested:
- Season-aggregate data model (NOT per-game frequency counts like NFL)
- Normal distribution via statistics.NormalDist (stdlib, no scipy)
- MIN_SAMPLE_GAMES = 20 gate (games threshold, not rows like NFL's 30)
- All Decimal fields wrapped with Decimal(str(round(x, 6))) — no raw float
- std floor of 0.5 prevents StatisticsError when avg_per_game = 0.0
- double_double uses inclusion-exclusion probability formula
"""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# These imports will fail until Task 3 creates the module (RED phase)
from sportsbet.prop.nba_executor import run_nba_prop_query, MIN_SAMPLE_GAMES
from sportsbet.graph.models import PropParams, PropResult


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


def make_mock_pool(
    total_games=60,
    total_stat=1500,
    avg_per_game=25.0,
    avg_pts=22.0,
    avg_reb=8.0,
    avg_ast=6.0,
):
    """Create a mock asyncpg pool that returns a Record-like dict from fetchrow."""
    row = {
        "total_games": total_games,
        "total_stat": total_stat,
        "avg_per_game": avg_per_game,
        "avg_pts": avg_pts,
        "avg_reb": avg_reb,
        "avg_ast": avg_ast,
    }
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    return pool


def test_insufficient_sample_returns_none_probability():
    """When mock pool returns total_games=5 (< MIN_SAMPLE_GAMES=20),
    PropResult.true_probability is None and data_source='insufficient_sample'."""
    pool = make_mock_pool(total_games=5)
    params = _make_nba_params(prop_type="points")
    result: PropResult = asyncio.run(run_nba_prop_query(pool, params))

    assert result.true_probability is None
    assert result.data_source == "insufficient_sample"


def test_adequate_sample_returns_decimal_probability():
    """When mock pool returns total_games=60, avg_per_game=25.0,
    PropResult.true_probability is a Decimal between 0.01 and 0.99."""
    pool = make_mock_pool(total_games=60, avg_per_game=25.0)
    params = _make_nba_params(prop_type="points", line=Decimal("25.5"))
    result: PropResult = asyncio.run(run_nba_prop_query(pool, params))

    assert result.true_probability is not None
    assert isinstance(result.true_probability, Decimal)
    assert Decimal("0.01") <= result.true_probability <= Decimal("0.99")


def test_decimal_wrapping_no_float():
    """PropResult.true_probability is an instance of Decimal, never float.
    Strict Pydantic model would reject raw float — this test enforces the
    Decimal(str(round(x, 6))) wrapping rule."""
    pool = make_mock_pool(total_games=60, avg_per_game=20.0)
    params = _make_nba_params(prop_type="points", line=Decimal("20.0"))
    result: PropResult = asyncio.run(run_nba_prop_query(pool, params))

    assert isinstance(result.true_probability, Decimal)
    assert not isinstance(result.true_probability, float)


def test_std_floor_prevents_zero_sigma():
    """When avg_per_game=0.0 (e.g. assists for a center), run_nba_prop_query
    does NOT raise StatisticsError — std floor of 0.5 prevents sigma=0."""
    pool = make_mock_pool(total_games=40, avg_per_game=0.0)
    params = _make_nba_params(prop_type="assists", line=Decimal("1.5"))
    # Should NOT raise StatisticsError — std floor of 0.5 prevents NormalDist(0, 0)
    result: PropResult = asyncio.run(run_nba_prop_query(pool, params))
    assert result.true_probability is not None


def test_pra_query_builds_composite_sql():
    """prop_type='pra' uses the PRA composite template (points+rebounds+assists),
    confirmed by verifying the correct SQL was called on the mock connection."""
    pool = make_mock_pool(total_games=55, avg_per_game=35.0)
    params = _make_nba_params(prop_type="pra", line=Decimal("35.5"))
    result: PropResult = asyncio.run(run_nba_prop_query(pool, params))

    # Extract the SQL that was called on the mock connection
    conn = pool.acquire.return_value.__aenter__.return_value
    called_sql = conn.fetchrow.call_args[0][0]

    sql_lower = called_sql.lower()
    assert "points" in sql_lower
    assert "rebounds" in sql_lower
    assert "assists" in sql_lower
    assert result.true_probability is not None


def test_double_double_returns_probability():
    """prop_type='double_double' with adequate sample returns PropResult with
    non-None true_probability — inclusion-exclusion formula produces valid Decimal."""
    pool = make_mock_pool(
        total_games=60,
        avg_pts=22.0,
        avg_reb=8.0,
        avg_ast=6.0,
    )
    params = _make_nba_params(prop_type="double_double", line=Decimal("0"))
    result: PropResult = asyncio.run(run_nba_prop_query(pool, params))

    assert result.true_probability is not None
    assert isinstance(result.true_probability, Decimal)
    assert Decimal("0.01") <= result.true_probability <= Decimal("0.99")


def test_games_played_zero_gate():
    """When SQL returns total_games=0, returns PropResult(data_source='insufficient_sample').
    Zero-games gate must fire before any probability computation."""
    pool = make_mock_pool(total_games=0)
    params = _make_nba_params(prop_type="points")
    result: PropResult = asyncio.run(run_nba_prop_query(pool, params))

    assert result.true_probability is None
    assert result.data_source == "insufficient_sample"
