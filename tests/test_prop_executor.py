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

PROP-04 (Plan 02):
4. test_kinematic_adjustment_applied     — rec_yds + geometric_mismatch_flag=True → +0.05 boost
5. test_kinematic_no_adjust_pass_prop   — pass_yds + flag=True → unchanged probability
6. test_kinematic_probability_clamped   — probability 0.97 + boost → clamped at 0.99
7. test_kinematic_none_returns_unchanged — kinematic=None → unchanged, no AttributeError
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from sportsbet.graph.models import PropParams, PropResult
from sportsbet.kinematic.models import KinematicAnalysis
from sportsbet.prop.agents import _apply_kinematic_adjustment

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
# PROP-04 kinematic integration tests (Plan 02)
# ---------------------------------------------------------------------------


def _make_kinematic(geometric_mismatch_flag: bool = True) -> KinematicAnalysis:
    """Return a minimal KinematicAnalysis for PROP-04 tests."""
    return KinematicAnalysis(
        season=2022,
        week=5,
        receiver_gsis_id="x",
        avg_separation=Decimal("3.1"),
        geometric_mismatch_flag=geometric_mismatch_flag,
    )


def test_kinematic_adjustment_applied() -> None:
    """rec_yds prop with geometric_mismatch_flag=True → true_probability boosted by 0.05."""
    result = PropResult(
        true_probability=Decimal("0.60"),
        sample_size=50,
        confidence_interval=(Decimal("0.50"), Decimal("0.70")),
        data_source="postgresql",
    )
    kinematic = _make_kinematic(geometric_mismatch_flag=True)
    adjusted = _apply_kinematic_adjustment(result, kinematic, "rec_yds")
    assert adjusted.true_probability == Decimal("0.65"), (
        f"Expected 0.65, got {adjusted.true_probability}"
    )
    assert adjusted.data_source == "postgresql+kinematic"


def test_kinematic_no_adjust_pass_prop() -> None:
    """pass_yds prop with geometric_mismatch_flag=True → true_probability unchanged (not a receiving prop)."""
    result = PropResult(
        true_probability=Decimal("0.60"),
        sample_size=50,
        confidence_interval=(Decimal("0.50"), Decimal("0.70")),
        data_source="postgresql",
    )
    kinematic = _make_kinematic(geometric_mismatch_flag=True)
    unchanged = _apply_kinematic_adjustment(result, kinematic, "pass_yds")
    assert unchanged.true_probability == Decimal("0.60"), (
        f"Expected 0.60 (unchanged), got {unchanged.true_probability}"
    )


def test_kinematic_probability_clamped() -> None:
    """rec_yds with probability 0.97 + 0.05 boost → clamped to 0.99, not 1.02."""
    result = PropResult(
        true_probability=Decimal("0.97"),
        sample_size=50,
        confidence_interval=(Decimal("0.90"), Decimal("0.99")),
        data_source="postgresql",
    )
    kinematic = _make_kinematic(geometric_mismatch_flag=True)
    adjusted = _apply_kinematic_adjustment(result, kinematic, "rec_yds")
    assert adjusted.true_probability == Decimal("0.99"), (
        f"Expected clamped 0.99, got {adjusted.true_probability}"
    )


def test_kinematic_none_returns_unchanged() -> None:
    """kinematic=None → PropResult returned unchanged, no AttributeError raised."""
    result = PropResult(
        true_probability=Decimal("0.60"),
        sample_size=50,
        confidence_interval=(Decimal("0.50"), Decimal("0.70")),
        data_source="postgresql",
    )
    unchanged = _apply_kinematic_adjustment(result, None, "rec_yds")
    assert unchanged.true_probability == Decimal("0.60"), (
        f"Expected 0.60 (unchanged), got {unchanged.true_probability}"
    )
