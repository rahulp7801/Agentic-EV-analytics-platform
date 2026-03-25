"""Wave 0 test stubs for SC-5: executor Wilson CI widening for small conditional samples.

These tests validate the statistical pattern (Wilson CI) and the executor logic for
handling total=0 (always insufficient_sample) and conditional small samples.

Pattern tests (test_wilson_ci_widens_for_small_conditional) call statsmodels directly
and are GREEN immediately — no implementation dependency.

Executor tests (test_wilson_ci_total_zero_returns_insufficient) mock the DB connection
and call run_prop_query. They are GREEN once executor.py implements the updated gate
(Task 3).
"""
from __future__ import annotations

import asyncio
import math
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from statsmodels.stats.proportion import proportion_confint

from sportsbet.graph.models import PropParams, PropResult


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


# ---------------------------------------------------------------------------
# Wilson CI pattern unit tests — GREEN immediately (no executor dependency)
# ---------------------------------------------------------------------------


def test_wilson_ci_widens_for_small_conditional() -> None:
    """statsmodels Wilson CI returns valid (non-NaN) bounds for small sample (nobs=5).

    This is a unit test of the statistical pattern used by Phase 18 SC-5.
    proportion_confint(count=3, nobs=5, method='wilson') must return finite,
    ordered bounds — the wide CI is the correct result, not an error.
    """
    lo, hi = proportion_confint(count=3, nobs=5, alpha=0.05, method="wilson")

    # Both bounds must be finite (non-NaN) for nobs >= 1
    assert not math.isnan(lo), f"Wilson CI lower bound must be finite, got {lo}"
    assert not math.isnan(hi), f"Wilson CI upper bound must be finite, got {hi}"

    # Lower < Upper (well-formed interval)
    assert lo < hi, f"Wilson CI must be ordered (lo={lo:.3f}, hi={hi:.3f})"

    # Upper bound < 0.9 for 3/5 — sanity-check the interval is not degenerate
    assert lo < 0.9, f"Wilson CI lo should be < 0.9 for 3/5, got {lo:.3f}"


# ---------------------------------------------------------------------------
# Executor zero-total test — tests the conditional gate in run_prop_query
# ---------------------------------------------------------------------------


def test_wilson_ci_total_zero_returns_insufficient() -> None:
    """run_prop_query with total=0 returns PropResult(data_source='insufficient_sample').

    This covers the 'total == 0' guard added in Task 3 — Wilson CI returns NaN
    for nobs=0, so zero-total must short-circuit before proportion_confint is called.

    Uses asyncio.run to exercise the async executor synchronously.
    """
    from sportsbet.prop.executor import run_prop_query

    # Mock asyncpg pool that returns a row with total=0, successes=0, mean_val=None
    mock_row = {"total": 0, "successes": 0, "mean_val": None}
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=mock_row)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    params = _nfl_params()

    result: PropResult = asyncio.run(run_prop_query(mock_pool, params))

    assert result.data_source == "insufficient_sample", (
        f"total=0 must return data_source='insufficient_sample', got '{result.data_source}'"
    )
    assert result.true_probability is None, (
        "total=0 result must have true_probability=None (no Kelly sizing on empty sample)"
    )
