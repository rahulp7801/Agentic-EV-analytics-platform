"""TDD tests for Phase 11 Plan 01: run_prop_query executor + PROP-04 kinematic stubs.

Wave 0: PROP-03 tests written RED — run_prop_query does not exist yet.
Wave 1 (Task 2): Implementation makes PROP-03 tests GREEN.
PROP-04 kinematic stub tests are marked xfail — Plan 02 implements kinematic integration.

Mock pool pattern mirrors test_quant.py: MagicMock pool with _async_cm context manager.
Live DB tests gated by SPORTSBET_TEST_DATABASE_URL environment variable (skipif).

Test inventory:
PROP-03:
1. test_adequate_sample          — 50-row mock → PropResult with Decimal fields
2. test_insufficient_sample      — 5-row mock → PropResult(data_source="insufficient_sample")
3. test_live_db                  — live DB run (skipped if no SPORTSBET_TEST_DATABASE_URL)

PROP-04 stubs (xfail — Plan 02):
4. test_kinematic_adjustment_applied
5. test_kinematic_no_adjust_pass_prop
6. test_kinematic_probability_clamped
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from sportsbet.graph.models import PropParams, PropResult

try:
    from sportsbet.prop.executor import MIN_PROP_SAMPLE_SIZE, run_prop_query
    _EXECUTOR_IMPORTED = True
except ImportError:
    run_prop_query = None  # type: ignore[assignment]
    MIN_PROP_SAMPLE_SIZE = 30
    _EXECUTOR_IMPORTED = False

_HAS_DB = bool(os.environ.get("SPORTSBET_TEST_DATABASE_URL"))


# ---------------------------------------------------------------------------
# Async context manager helper for mocking pool.acquire()
# (same pattern as test_quant.py _async_cm)
# ---------------------------------------------------------------------------

class _async_cm:  # noqa: N801
    """Minimal async context manager wrapping a mock connection."""

    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self._conn

    async def __aexit__(self, *args: object) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _valid_prop_params(**overrides: object) -> PropParams:
    """Return a minimal valid PropParams with optional field overrides."""
    base: dict[str, object] = {
        "game_id": "2023_01_KC_DET",
        "player_id": "00-0033873",
        "season": 2023,
        "sport": "nfl",
        "prop_type": "pass_yds",
        "line": Decimal("250"),
        "filters": {},
    }
    base.update(overrides)
    return PropParams(**base)  # type: ignore[arg-type]


def _make_mock_pool(row: dict) -> MagicMock:
    """Build a MagicMock pool that returns the given row from conn.fetchrow()."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))
    return mock_pool


# ---------------------------------------------------------------------------
# PROP-03 tests
# ---------------------------------------------------------------------------


def test_adequate_sample() -> None:
    """Mock pool returning total=50, successes=30, mean_val=245.6 → PropResult with Decimal fields."""
    if not _EXECUTOR_IMPORTED:
        pytest.fail("run_prop_query not importable — implementation not yet provided (Wave 0 RED)")

    mock_pool = _make_mock_pool({"total": 50, "successes": 30, "mean_val": 245.6})
    params = _valid_prop_params()

    result: PropResult = asyncio.run(run_prop_query(mock_pool, params))  # type: ignore[arg-type]

    assert result.data_source == "postgresql"
    assert result.sample_size == 50
    assert isinstance(result.true_probability, Decimal), "true_probability must be Decimal, not float"
    assert result.confidence_interval is not None, "confidence_interval must be set for adequate sample"
    lo, hi = result.confidence_interval
    assert isinstance(lo, Decimal), "CI lower bound must be Decimal (not float)"
    assert isinstance(hi, Decimal), "CI upper bound must be Decimal (not float)"
    assert lo < hi, "CI lower must be less than upper"
    assert result.true_probability == Decimal("0.6"), "30/50 = 0.6"
    assert isinstance(result.mean_stat, Decimal), "mean_stat must be Decimal (not float)"


def test_insufficient_sample() -> None:
    """Mock pool returning total=5, successes=3, mean_val=100.0 → insufficient_sample PropResult."""
    if not _EXECUTOR_IMPORTED:
        pytest.fail("run_prop_query not importable — implementation not yet provided (Wave 0 RED)")

    mock_pool = _make_mock_pool({"total": 5, "successes": 3, "mean_val": 100.0})
    params = _valid_prop_params()

    result: PropResult = asyncio.run(run_prop_query(mock_pool, params))  # type: ignore[arg-type]

    assert result.data_source == "insufficient_sample"
    assert result.true_probability is None
    assert result.sample_size == 5


@pytest.mark.skipif(
    not _HAS_DB,
    reason="SPORTSBET_TEST_DATABASE_URL not set — skipping live DB test",
)
async def test_live_db() -> None:
    """Live DB: run_prop_query for a known player returns PropResult with non-None true_probability."""
    from sportsbet.db.connection import create_async_pool

    pool = await create_async_pool(min_size=1, max_size=2)
    try:
        params = _valid_prop_params(
            player_id="00-0033873",
            season=2020,
            prop_type="pass_yds",
            line=Decimal("250"),
        )
        result = await run_prop_query(pool, params)  # type: ignore[arg-type]
        # If insufficient data for this player/season, data_source may be "insufficient_sample"
        # The key assertion is that the function returns a valid PropResult (no exception)
        assert isinstance(result, PropResult)
        assert result.data_source in ("postgresql", "insufficient_sample")
    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# PROP-04 kinematic stub tests (xfail — Plan 02 implements kinematic integration)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="Plan 02 implements kinematic adjustment in make_prop_quant_agent")
def test_kinematic_adjustment_applied() -> None:
    """Kinematic-adjusted PropResult has probability different from base when geometric mismatch flagged."""
    # Plan 02: make_prop_quant_agent passes real KinematicAnalysis to _apply_kinematic_adjustment.
    # When geometric_mismatch_flag=True, probability is adjusted. This test verifies that behavior.
    raise NotImplementedError("Plan 02 fills in kinematic adjustment — stub in Plan 01")


@pytest.mark.xfail(reason="Plan 02 implements kinematic adjustment in make_prop_quant_agent")
def test_kinematic_no_adjust_pass_prop() -> None:
    """Kinematic does NOT adjust pass_yds props — adjustment only applies to receiving props."""
    # Plan 02: _apply_kinematic_adjustment returns result unchanged when prop_type is pass-side.
    raise NotImplementedError("Plan 02 fills in kinematic adjustment — stub in Plan 01")


@pytest.mark.xfail(reason="Plan 02 implements kinematic adjustment in make_prop_quant_agent")
def test_kinematic_probability_clamped() -> None:
    """Kinematic-adjusted probability is clamped to [0.01, 0.99] — never exactly 0 or 1."""
    # Plan 02: _apply_kinematic_adjustment applies a delta and clamps the result.
    raise NotImplementedError("Plan 02 fills in kinematic adjustment — stub in Plan 01")
