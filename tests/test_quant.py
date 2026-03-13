"""Tests for Phase 3 Plan 01: Quant subpackage — QueryBuilder and executor.

RED phase: all tests fail until implementation is provided.
Integration tests requiring a live PostgreSQL instance are gated by
SPORTSBET_TEST_DATABASE_URL env var (skipif, not xfail).

Test inventory:
1. test_quant_params_validation          — QuantParams rejects season < 1999
2. test_quant_params_sql_injection       — QuantParams rejects non-Literal stat_type
3. test_query_builder_parameterized      — build() returns $1/$2 placeholders; values not in SQL
4. test_query_builder_filter_key_guard   — unknown filter keys silently dropped
5. test_run_quant_query_passing          — live DB integration (skipif no DB)
6. test_quant_agent_live                 — live graph ainvoke integration (skipif no DB)
7. test_insufficient_sample              — mock pool with 0 rows → insufficient_sample
8. test_run_quant_query_mock_adequate_sample — mock pool with 50 rows → real Decimal CI
"""
from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from sportsbet.graph.models import QuantParams, QuantResult

try:
    from sportsbet.quant.query_builder import QueryBuilder
    _QUERY_BUILDER_IMPORTED = True
except ImportError:
    QueryBuilder = None  # type: ignore[assignment, misc]
    _QUERY_BUILDER_IMPORTED = False

try:
    from sportsbet.quant.executor import MIN_SAMPLE_SIZE, run_quant_query
    _EXECUTOR_IMPORTED = True
except ImportError:
    run_quant_query = None  # type: ignore[assignment]
    MIN_SAMPLE_SIZE = 30
    _EXECUTOR_IMPORTED = False

_HAS_DB = bool(os.environ.get("SPORTSBET_TEST_DATABASE_URL"))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _valid_params(**overrides: object) -> QuantParams:
    """Return a minimal valid QuantParams with optional field overrides."""
    base: dict[str, object] = {
        "game_id": "2023_01_KC_DET",
        "season": 2023,
        "week": 1,
        "posteam": "KC",
        "stat_type": "passing",
        "filters": {},
    }
    base.update(overrides)
    return QuantParams(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Unit tests — no DB required
# ---------------------------------------------------------------------------


def test_quant_params_validation() -> None:
    """QuantParams with season=1998 must raise ValidationError (ge=1999 constraint)."""
    with pytest.raises(ValidationError):
        QuantParams(
            game_id="x",
            season=1998,
            week=1,
            posteam="KC",
            stat_type="passing",
            filters={},
        )


def test_quant_params_sql_injection() -> None:
    """QuantParams with stat_type outside Literal raises ValidationError."""
    with pytest.raises(ValidationError):
        QuantParams(
            game_id="x",
            season=2023,
            week=1,
            posteam="KC",
            stat_type="passing'; DROP TABLE--",  # type: ignore[arg-type]
            filters={},
        )


def test_query_builder_parameterized() -> None:
    """QueryBuilder.build() returns (str, tuple) with $1 placeholder; posteam not in SQL."""
    if not _QUERY_BUILDER_IMPORTED:
        pytest.fail("QueryBuilder not importable — not implemented yet")
    params = _valid_params()
    sql, args = QueryBuilder.build(params)  # type: ignore[union-attr]
    assert isinstance(sql, str), "build() must return a str as first element"
    assert isinstance(args, tuple), "build() must return a tuple as second element"
    assert "$1" in sql, "SQL must use $1 positional placeholder"
    assert "KC" not in sql, "posteam value must not appear in the SQL string"


def test_query_builder_filter_key_guard() -> None:
    """Unknown filter keys are silently dropped; no KeyError, no SQL injection."""
    if not _QUERY_BUILDER_IMPORTED:
        pytest.fail("QueryBuilder not importable — not implemented yet")
    params = _valid_params(filters={"evil_col": "val", "down": 3})
    sql, args = QueryBuilder.build(params)  # type: ignore[union-attr]
    assert "evil_col" not in sql, "Unknown filter key must not appear in SQL"
    assert "val" not in args, "Unknown filter value must not appear in args"
    # "down" IS allowed — its param value (3) must be in args
    assert 3 in args, "Allowed filter value must appear in args tuple"


def test_insufficient_sample() -> None:
    """run_quant_query with 0-row result returns insufficient_sample QuantResult."""
    if not _EXECUTOR_IMPORTED:
        pytest.fail("run_quant_query not importable — not implemented yet")

    # Build a mock asyncpg pool that returns a row with total=0, successes=0
    mock_row = {"total": 0, "successes": 0}
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=mock_row)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=_async_cm(mock_conn)
    )

    params = _valid_params()

    import asyncio
    result: QuantResult = asyncio.get_event_loop().run_until_complete(
        run_quant_query(mock_pool, params)  # type: ignore[arg-type]
    )
    assert result.data_source == "insufficient_sample"
    assert result.true_probability is None
    assert result.sample_size == 0


def test_run_quant_query_mock_adequate_sample() -> None:
    """Mock pool returning total=50, successes=30 → real Decimal CI, no DB required."""
    if not _EXECUTOR_IMPORTED:
        pytest.fail("run_quant_query not importable — not implemented yet")

    mock_row = {"total": 50, "successes": 30}
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=mock_row)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=_async_cm(mock_conn)
    )

    params = _valid_params()

    import asyncio
    result: QuantResult = asyncio.get_event_loop().run_until_complete(
        run_quant_query(mock_pool, params)  # type: ignore[arg-type]
    )
    assert result.data_source == "postgresql"
    assert result.sample_size == 50
    assert isinstance(result.true_probability, Decimal), "true_probability must be Decimal"
    assert result.confidence_interval is not None
    lo, hi = result.confidence_interval
    assert isinstance(lo, Decimal), "CI lower bound must be Decimal (not float)"
    assert isinstance(hi, Decimal), "CI upper bound must be Decimal (not float)"
    assert lo < hi, "CI lower bound must be less than upper bound"
    assert result.true_probability == Decimal("0.6"), "30/50 = 0.6"


# ---------------------------------------------------------------------------
# Integration tests — require live DB
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_DB, reason="SPORTSBET_TEST_DATABASE_URL not set")
async def test_run_quant_query_passing() -> None:
    """Live DB: run_quant_query returns QuantResult with non-None sample_size."""
    from sportsbet.db.connection import create_async_pool

    pool = await create_async_pool(min_size=1, max_size=2)
    try:
        params = _valid_params()
        result = await run_quant_query(pool, params)  # type: ignore[arg-type]
        assert result.sample_size is not None
    finally:
        await pool.close()


@pytest.mark.skipif(not _HAS_DB, reason="SPORTSBET_TEST_DATABASE_URL not set")
async def test_quant_agent_live() -> None:
    """Live DB: graph ainvoke with real pool returns quant_result.data_source != fixture."""
    import uuid

    from langgraph.checkpoint.memory import MemorySaver

    from sportsbet.db.connection import create_async_pool
    from sportsbet.graph.agents import make_quant_agent
    from sportsbet.graph.graph import create_graph

    pool = await create_async_pool(min_size=1, max_size=2)
    try:
        real_agent = make_quant_agent(pool)
        graph = create_graph(checkpointer=MemorySaver(), quant_node=real_agent)
        state = {
            "session_id": str(uuid.uuid4()),
            "request_type": "quant",
            "game_id": "2023_01_KC_DET",
            "season": 2023,
            "week": 1,
            "home_team": "DET",
            "away_team": "KC",
            "injury_flags": {},
            "weather_json": None,
            "error": None,
            "quant_result": None,
            "ev_signal": None,
        }
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = await graph.ainvoke(state, config=config)
        assert result["quant_result"].data_source != "fixture"
    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# Async context manager helper for mocking pool.acquire()
# ---------------------------------------------------------------------------

class _async_cm:  # noqa: N801
    """Minimal async context manager wrapping a mock connection."""

    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self._conn

    async def __aexit__(self, *args: object) -> None:
        pass
