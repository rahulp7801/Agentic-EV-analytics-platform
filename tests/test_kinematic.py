"""Tests for Phase 6: Kinematic subpackage — models, availability, matchup, and graph wiring.

Covers KINE-01, KINE-02, and KINE-03.

Test inventory (Plan 01 — unit tests):
1. test_kinematic_params_rejects_pre_ngs_season  — season=2015 raises ValidationError (KINE-03)
2. test_kinematic_params_accepts_2016            — season=2016 validates without error (KINE-03)
3. test_unavailable_season_returns_none_fields   — check_ngs_availability returns False for
                                                   count=0 pool; make_kinematic_agent returns
                                                   {"kinematic_result": None} when unavailable
4. test_matchup_query_returns_ngs_fields         — run_matchup_query with mock pool returns
                                                   KinematicAnalysis with correct Decimal fields
5. test_mismatch_flag_set_on_high_separation     — geometric_mismatch_flag=True when
                                                   avg_separation >= SEPARATION_THRESHOLD
6. test_kinematic_analysis_has_no_quant_fields   — KinematicAnalysis has no true_probability,
                                                   sample_size, or confidence_interval fields

Test inventory (Plan 02 — integration tests):
7. test_make_kinematic_agent_end_to_end          — graph.ainvoke with kinematic_node returns
                                                   KinematicAnalysis with ngs_available=True
8. test_kinematic_agent_unavailable_season       — graph.ainvoke with count=0 pool returns
                                                   kinematic_result=None (not an exception)
9. test_kinematic_agent_independence             — KinematicAnalysis has no true_probability,
                                                   kelly_fraction, or sample_size fields
10. test_route_kinematic_analysis               — create_graph stub routes kinematic_analysis
                                                   without error

All asyncpg pool calls are mocked — no live DB required.
MagicMock (not AsyncMock) for pool.acquire() — matches Phase 4 decision.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from sportsbet.kinematic.models import KinematicAnalysis, KinematicParams


# ---------------------------------------------------------------------------
# Async context manager helper (matches _async_cm pattern in test_quant.py)
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
# Test 1: KinematicParams rejects pre-NGS season (KINE-03)
# ---------------------------------------------------------------------------


def test_kinematic_params_rejects_pre_ngs_season() -> None:
    """KinematicParams with season=2015 must raise ValidationError (ge=2016 constraint).

    NGS data is only available from 2016. Season 2015 must be rejected by Pydantic
    before any DB query executes — the guard is at the validation layer, not the DB.
    """
    with pytest.raises(ValidationError):
        KinematicParams(season=2015, week=1, receiver_gsis_id="00-0034796")


# ---------------------------------------------------------------------------
# Test 2: KinematicParams accepts 2016 (KINE-03)
# ---------------------------------------------------------------------------


def test_kinematic_params_accepts_2016() -> None:
    """KinematicParams with season=2016 must validate successfully.

    2016 is the first season of NGS data availability. Pydantic ge=2016 constraint
    must accept this boundary value.
    """
    params = KinematicParams(season=2016, week=1, receiver_gsis_id="00-0034796")
    assert params.season == 2016
    assert params.week == 1
    assert params.receiver_gsis_id == "00-0034796"
    assert params.min_targets == 10  # default


# ---------------------------------------------------------------------------
# Test 3: Unavailable season returns None fields (KINE-03)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unavailable_season_returns_none_fields() -> None:
    """check_ngs_availability returns False for a season with zero non-null avg_separation rows.

    When the pool returns count=0, check_ngs_availability must return False (not raise).
    When make_kinematic_agent is called with a pool that reports unavailability,
    the agent returns {"kinematic_result": None}.

    Mock: pool.acquire() returns a conn whose fetchrow returns {"n": 0}.
    """
    from sportsbet.kinematic.availability import check_ngs_availability
    from sportsbet.graph.agents import make_kinematic_agent

    # Build mock pool returning count=0 for availability check
    mock_conn_avail = AsyncMock()
    mock_conn_avail.fetchrow = AsyncMock(return_value={"n": 0})
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn_avail))

    # Part 1: check_ngs_availability returns False
    result = await check_ngs_availability(mock_pool, season=2024)
    assert result is False, "check_ngs_availability must return False when count=0"

    # Part 2: make_kinematic_agent returns {"kinematic_result": None} when unavailable
    import uuid
    from datetime import datetime, timezone

    state = {
        "session_id": str(uuid.uuid4()),
        "request_type": "kinematic_analysis",
        "game_id": "2024_01_KC_LAC",
        "season": 2024,
        "week": 1,
        "home_team": "KC",
        "away_team": "LAC",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "context_signals": None,
        "kinematic_result": None,
        "receiver_gsis_id": "00-0034796",
    }

    # Reset mock for the agent call (availability check runs again inside agent)
    mock_conn_agent = AsyncMock()
    mock_conn_agent.fetchrow = AsyncMock(return_value={"n": 0})
    mock_pool_agent = MagicMock()
    mock_pool_agent.acquire = MagicMock(return_value=_async_cm(mock_conn_agent))

    agent = make_kinematic_agent(mock_pool_agent)
    agent_result = await agent(state)

    assert isinstance(agent_result, dict), "Agent must return a dict"
    assert "kinematic_result" in agent_result, "Return dict must contain 'kinematic_result'"
    assert agent_result["kinematic_result"] is None, (
        "kinematic_result must be None when NGS data unavailable"
    )


# ---------------------------------------------------------------------------
# Test 4: run_matchup_query returns correct NGS fields (KINE-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matchup_query_returns_ngs_fields() -> None:
    """run_matchup_query with mock pool returns KinematicAnalysis with correct Decimal fields.

    Mock pool returns a row with season_avg_separation=2.3, season_avg_cushion=1.1,
    weeks_sampled=5. The result must have:
    - avg_separation = Decimal("2.3")
    - avg_cushion = Decimal("1.1")
    - ngs_available = True
    - press_man_rate = None (always None — forward-compat only)
    """
    from sportsbet.kinematic.matchup import run_matchup_query

    mock_row = {
        "season_avg_separation": Decimal("2.3"),
        "season_avg_cushion": Decimal("1.1"),
        "avg_time_to_throw": None,
        "weeks_sampled": 5,
    }
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=mock_row)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

    params = KinematicParams(season=2024, week=5, receiver_gsis_id="00-0034796")
    analysis = await run_matchup_query(mock_pool, params)

    assert isinstance(analysis, KinematicAnalysis), "Must return KinematicAnalysis"
    assert analysis.avg_separation == Decimal("2.3"), (
        f"avg_separation must be Decimal('2.3'), got {analysis.avg_separation}"
    )
    assert analysis.avg_cushion == Decimal("1.1"), (
        f"avg_cushion must be Decimal('1.1'), got {analysis.avg_cushion}"
    )
    assert analysis.ngs_available is True, "ngs_available must be True when row returned"
    assert analysis.press_man_rate is None, (
        "press_man_rate must always be None — forward-compat placeholder only"
    )


# ---------------------------------------------------------------------------
# Test 5: geometric_mismatch_flag computed from threshold (KINE-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mismatch_flag_set_on_high_separation() -> None:
    """geometric_mismatch_flag=True when avg_separation >= SEPARATION_THRESHOLD.

    Uses two mock pool calls:
    - avg_separation=3.0 (>= 2.5 threshold) -> geometric_mismatch_flag=True
    - avg_separation=1.8 (< 2.5 threshold) -> geometric_mismatch_flag=False
    """
    from sportsbet.kinematic.matchup import SEPARATION_THRESHOLD, run_matchup_query

    assert SEPARATION_THRESHOLD == Decimal("2.5"), (
        f"SEPARATION_THRESHOLD must be Decimal('2.5'), got {SEPARATION_THRESHOLD}"
    )

    # High separation — flag should be True
    mock_row_high = {
        "season_avg_separation": Decimal("3.0"),
        "season_avg_cushion": Decimal("1.5"),
        "avg_time_to_throw": None,
        "weeks_sampled": 8,
    }
    mock_conn_high = AsyncMock()
    mock_conn_high.fetchrow = AsyncMock(return_value=mock_row_high)
    mock_pool_high = MagicMock()
    mock_pool_high.acquire = MagicMock(return_value=_async_cm(mock_conn_high))

    params = KinematicParams(season=2024, week=5, receiver_gsis_id="00-0034796")
    analysis_high = await run_matchup_query(mock_pool_high, params)
    assert analysis_high.geometric_mismatch_flag is True, (
        f"avg_sep=3.0 >= threshold=2.5 must set flag=True, got {analysis_high.geometric_mismatch_flag}"
    )

    # Low separation — flag should be False
    mock_row_low = {
        "season_avg_separation": Decimal("1.8"),
        "season_avg_cushion": Decimal("1.0"),
        "avg_time_to_throw": None,
        "weeks_sampled": 8,
    }
    mock_conn_low = AsyncMock()
    mock_conn_low.fetchrow = AsyncMock(return_value=mock_row_low)
    mock_pool_low = MagicMock()
    mock_pool_low.acquire = MagicMock(return_value=_async_cm(mock_conn_low))

    analysis_low = await run_matchup_query(mock_pool_low, params)
    assert analysis_low.geometric_mismatch_flag is False, (
        f"avg_sep=1.8 < threshold=2.5 must set flag=False, got {analysis_low.geometric_mismatch_flag}"
    )


# ---------------------------------------------------------------------------
# Test 6: KinematicAnalysis has no QuantResult fields (independence check)
# ---------------------------------------------------------------------------


def test_kinematic_analysis_has_no_quant_fields() -> None:
    """KinematicAnalysis must not have true_probability, sample_size, or confidence_interval.

    These fields belong to QuantResult (Phase 3). KinematicAnalysis is an independent
    geometric signal model — it must never depend on or replicate QuantResult fields.
    dir() check confirms structural independence.
    """
    analysis = KinematicAnalysis(
        season=2024,
        week=5,
        receiver_gsis_id="00-0034796",
    )
    fields = set(KinematicAnalysis.model_fields.keys())

    assert "true_probability" not in fields, (
        "KinematicAnalysis must not have true_probability (belongs to QuantResult)"
    )
    assert "sample_size" not in fields, (
        "KinematicAnalysis must not have sample_size (belongs to QuantResult)"
    )
    assert "confidence_interval" not in fields, (
        "KinematicAnalysis must not have confidence_interval (belongs to QuantResult)"
    )
    # Confirm press_man_rate is present but always None
    assert "press_man_rate" in fields, "press_man_rate field must exist (forward-compat)"
    assert analysis.press_man_rate is None, "press_man_rate must be None by default"


# ---------------------------------------------------------------------------
# Integration Tests (Plan 02) — graph wiring, routing, end-to-end ainvoke
# ---------------------------------------------------------------------------


def _make_initial_state(request_type: str = "kinematic_analysis") -> dict:
    """Build a minimal GraphState dict for integration tests."""
    import uuid
    from datetime import datetime, timezone

    return {
        "session_id": str(uuid.uuid4()),
        "request_type": request_type,
        "created_at": datetime.now(timezone.utc),
        "game_id": "2023_05_KC_LAC",
        "season": 2023,
        "week": 5,
        "home_team": "KC",
        "away_team": "LAC",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "context_signals": None,
        "pending_signals": [],
        "cleared_signals": [],
        "kinematic_result": None,
    }


def _make_two_call_pool(avail_row: dict, matchup_row: dict | None) -> MagicMock:
    """Return a mock pool that serves avail_row on first acquire and matchup_row on second.

    Availability check (COUNT query) uses fetchrow once.
    Matchup query uses fetchrow once.
    Each pool.acquire() call returns a fresh _async_cm wrapping a new conn.
    """
    conn_avail = AsyncMock()
    conn_avail.fetchrow = AsyncMock(return_value=avail_row)

    conn_matchup = AsyncMock()
    conn_matchup.fetchrow = AsyncMock(return_value=matchup_row)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        side_effect=[_async_cm(conn_avail), _async_cm(conn_matchup)]
    )
    return mock_pool


# ---------------------------------------------------------------------------
# Test 7: end-to-end graph.ainvoke with real kinematic_node (KINE-02)
# ---------------------------------------------------------------------------


def test_make_kinematic_agent_end_to_end() -> None:
    """graph.ainvoke with request_type='kinematic_analysis' and real kinematic_node returns
    KinematicAnalysis with ngs_available=True, avg_separation=Decimal('2.8'),
    geometric_mismatch_flag=True (2.8 >= 2.5), press_man_rate=None.

    Uses MemorySaver checkpointer for full isolation.
    Mock pool: avail count=5 (available), separation=2.8 (above threshold).
    """
    import uuid

    from langgraph.checkpoint.memory import MemorySaver

    from sportsbet.graph.agents import make_kinematic_agent
    from sportsbet.graph.graph import create_graph

    avail_row = {"n": 5}
    matchup_row = {
        "season_avg_separation": Decimal("2.8"),
        "season_avg_cushion": Decimal("1.2"),
        "avg_time_to_throw": None,
        "weeks_sampled": 8,
    }
    mock_pool = _make_two_call_pool(avail_row, matchup_row)

    graph = create_graph(
        checkpointer=MemorySaver(),
        kinematic_node=make_kinematic_agent(mock_pool),
    )
    initial_state = _make_initial_state("kinematic_analysis")
    result = asyncio.run(
        graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )
    )

    kinematic_result = result.get("kinematic_result")
    assert kinematic_result is not None, (
        "kinematic_result must be populated after kinematic_analysis request"
    )
    assert isinstance(kinematic_result, KinematicAnalysis), (
        f"kinematic_result must be KinematicAnalysis, got {type(kinematic_result)}"
    )
    assert kinematic_result.ngs_available is True, "ngs_available must be True"
    assert kinematic_result.avg_separation == Decimal("2.8"), (
        f"avg_separation must be Decimal('2.8'), got {kinematic_result.avg_separation}"
    )
    assert kinematic_result.geometric_mismatch_flag is True, (
        "2.8 >= 2.5 threshold must set geometric_mismatch_flag=True"
    )
    assert kinematic_result.press_man_rate is None, (
        "press_man_rate must always be None"
    )


# ---------------------------------------------------------------------------
# Test 8: graph.ainvoke with unavailable NGS season returns kinematic_result=None (KINE-03)
# ---------------------------------------------------------------------------


def test_kinematic_agent_unavailable_season() -> None:
    """graph.ainvoke with mock pool returning count=0 returns kinematic_result=None.

    Confirms the availability guard fires correctly through the graph:
    no exception is raised, result is clean None.
    """
    import uuid

    from langgraph.checkpoint.memory import MemorySaver

    from sportsbet.graph.agents import make_kinematic_agent
    from sportsbet.graph.graph import create_graph

    # count=0 — NGS unavailable; no matchup row needed
    avail_row = {"n": 0}
    mock_conn_avail = AsyncMock()
    mock_conn_avail.fetchrow = AsyncMock(return_value=avail_row)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn_avail))

    graph = create_graph(
        checkpointer=MemorySaver(),
        kinematic_node=make_kinematic_agent(mock_pool),
    )
    initial_state = _make_initial_state("kinematic_analysis")
    result = asyncio.run(
        graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )
    )

    kinematic_result = result.get("kinematic_result")
    assert kinematic_result is None, (
        f"kinematic_result must be None when NGS unavailable, got {kinematic_result}"
    )


# ---------------------------------------------------------------------------
# Test 9: KinematicAnalysis independence from QuantResult fields
# ---------------------------------------------------------------------------


def test_kinematic_agent_independence() -> None:
    """KinematicAnalysis does not have QuantResult-specific fields.

    Confirms structural independence: true_probability, sample_size,
    confidence_interval, and kelly_fraction must not be attributes on
    KinematicAnalysis instances.
    """
    analysis = KinematicAnalysis(
        season=2023,
        week=5,
        receiver_gsis_id="00-0034796",
        avg_separation=Decimal("2.8"),
        geometric_mismatch_flag=True,
    )
    assert not hasattr(analysis, "true_probability"), (
        "KinematicAnalysis must not have true_probability"
    )
    assert not hasattr(analysis, "sample_size"), (
        "KinematicAnalysis must not have sample_size"
    )
    assert not hasattr(analysis, "confidence_interval"), (
        "KinematicAnalysis must not have confidence_interval"
    )
    assert not hasattr(analysis, "kelly_fraction"), (
        "KinematicAnalysis must not have kelly_fraction"
    )


# ---------------------------------------------------------------------------
# Test 10: route_from_master returns 'kinematic_agent' for kinematic_analysis
# ---------------------------------------------------------------------------


def test_route_kinematic_analysis() -> None:
    """create_graph(checkpointer=MemorySaver()) stub routes kinematic_analysis cleanly.

    Invokes graph with request_type='kinematic_analysis' and no kinematic_node
    (uses _kinematic_stub). Confirms no 'unknown_request_type' error is set
    and the graph terminates cleanly.

    Also tests route_from_master directly for the kinematic_analysis request_type.
    """
    import uuid

    from langgraph.checkpoint.memory import MemorySaver

    from sportsbet.graph.graph import create_graph
    from sportsbet.graph.router import route_from_master

    # Direct router test
    mock_state: dict = {
        "request_type": "kinematic_analysis",
        "session_id": "test-session",
        "error": None,
    }
    route = route_from_master(mock_state)  # type: ignore[arg-type]
    assert route == "kinematic_agent", (
        f"route_from_master must return 'kinematic_agent' for kinematic_analysis, got {route!r}"
    )

    # End-to-end graph stub test
    graph = create_graph(checkpointer=MemorySaver())  # no kinematic_node → stub
    initial_state = _make_initial_state("kinematic_analysis")
    result = asyncio.run(
        graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )
    )
    assert result.get("error") is None, (
        f"Stub route must not set error, got: {result.get('error')}"
    )
