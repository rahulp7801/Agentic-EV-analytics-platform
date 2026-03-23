"""Integration tests for prop pipeline wiring (Phase 13, Plan 02).

Tests confirm:
  - route_from_master routes nba_prop_analysis -> nba_quant_agent
  - route_from_master routes prop_arbitrage_analysis -> prop_arbitrage_agent
  - create_graph() accepts and compiles with prop_quant_node, nba_quant_node, prop_arbitrage_node
  - End-to-end NFL prop pipeline (pre-injected PropResult) produces non-None EVSignal
  - End-to-end NBA prop pipeline (pre-injected nba_prop_result) produces non-None EVSignal
  - Direct prop_arbitrage_analysis route (bypass quant) produces non-None EVSignal
  - All three new nodes are reachable in the compiled graph (via graph.nodes)

TDD: all tests written RED before implementation. After Task 2 extends router.py and
graph.py, all tests must turn GREEN.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from langgraph.checkpoint.memory import MemorySaver

from sportsbet.graph.models import (
    AgentOddsSnapshot,
    ContextSignals,
    PropResult,
)
from sportsbet.graph.router import route_from_master
from sportsbet.graph.graph import create_graph
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.graph.graph import make_correlation_guard_node, make_aggregator_node


# ---------------------------------------------------------------------------
# Stub nodes (no DB — pre-injected state passes through unchanged)
# ---------------------------------------------------------------------------

def _nfl_stub(state):  # type: ignore[type-arg]
    """NFL prop quant stub: prop_result already injected in initial state."""
    return {}


def _nba_stub(state):  # type: ignore[type-arg]
    """NBA prop quant stub: nba_prop_result already injected in initial state."""
    return {}


# ---------------------------------------------------------------------------
# Shared state factories
# ---------------------------------------------------------------------------

def _make_base_state(**overrides) -> dict:  # type: ignore[type-arg]
    """Return a full GraphState dict with all required fields."""
    base = {
        "session_id": str(uuid.uuid4()),
        "request_type": "prop_analysis",
        "created_at": datetime.now(timezone.utc),
        "game_id": "2024_01_KC_LV",
        "season": 2024,
        "week": 1,
        "home_team": "KC",
        "away_team": "LV",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "context_signals": ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=AgentOddsSnapshot(
                game_id="2024_01_KC_LV",
                sportsbook="draftkings",
                market_type="over_pass_yds",
                implied_probability=Decimal("0.50"),
                snapped_at=datetime.now(timezone.utc),
            ),
            signals_captured_at=datetime.now(timezone.utc),
        ),
        "prop_result": PropResult(
            true_probability=Decimal("0.62"),
            sample_size=45,
            confidence_interval=(Decimal("0.54"), Decimal("0.70")),
            data_source="postgresql",
            mean_stat=Decimal("265.0"),
        ),
        "nba_prop_result": None,
        "pending_signals": [],
        "cleared_signals": [],
        "receiver_gsis_id": "",
        "kinematic_result": None,
        "prop_type": "pass_yds",
        "prop_line": "250.5",
        "nba_context_signals": None,
    }
    base.update(overrides)
    return base


def _make_nfl_e2e_state() -> dict:  # type: ignore[type-arg]
    """Full NFL e2e state as specified in plan."""
    return _make_base_state(request_type="prop_analysis")


def _make_nba_e2e_state() -> dict:  # type: ignore[type-arg]
    """Full NBA e2e state with nba_prop_result set and nba_prop_analysis route."""
    nba_prop_result = PropResult(
        true_probability=Decimal("0.62"),
        sample_size=30,
        confidence_interval=(Decimal("0.54"), Decimal("0.70")),
        data_source="postgresql",
        mean_stat=Decimal("22.5"),
    )
    return _make_base_state(
        request_type="nba_prop_analysis",
        nba_prop_result=nba_prop_result,
        context_signals=ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=AgentOddsSnapshot(
                game_id="2024_01_KC_LV",
                sportsbook="draftkings",
                market_type="over_points",
                implied_probability=Decimal("0.50"),
                snapped_at=datetime.now(timezone.utc),
            ),
            signals_captured_at=datetime.now(timezone.utc),
        ),
        prop_type="points",
        prop_line="22.5",
    )


# ---------------------------------------------------------------------------
# Task 1 Tests — Router extension (RED)
# ---------------------------------------------------------------------------

class TestRouterExtension:
    """Tests for new route_from_master routes added in Task 2."""

    def test_route_nba_prop_analysis(self) -> None:
        """route_from_master with request_type='nba_prop_analysis' returns 'nba_quant_agent'."""
        state = _make_base_state(request_type="nba_prop_analysis")
        result = route_from_master(state)
        assert result == "nba_quant_agent", (
            f"Expected 'nba_quant_agent', got '{result}'"
        )

    def test_route_prop_arbitrage_analysis(self) -> None:
        """route_from_master with request_type='prop_arbitrage_analysis' returns 'prop_arbitrage_agent'."""
        state = _make_base_state(request_type="prop_arbitrage_analysis")
        result = route_from_master(state)
        assert result == "prop_arbitrage_agent", (
            f"Expected 'prop_arbitrage_agent', got '{result}'"
        )


# ---------------------------------------------------------------------------
# Task 1 Tests — Graph compilation with prop nodes (RED)
# ---------------------------------------------------------------------------

class TestCreateGraphAcceptsPropNodes:
    """Tests for create_graph() accepting new prop node parameters."""

    def test_create_graph_accepts_prop_nodes(self) -> None:
        """create_graph() with prop_quant_node, nba_quant_node, prop_arbitrage_node compiles."""
        prop_arb_node = make_prop_arbitrage_agent(sport="nfl")
        graph = create_graph(
            checkpointer=MemorySaver(),
            prop_quant_node=_nfl_stub,
            nba_quant_node=_nba_stub,
            prop_arbitrage_node=prop_arb_node,
        )
        # Compiled graph must expose nodes dict
        assert graph is not None, "create_graph() returned None"

    def test_conditional_edges_contain_prop_nodes(self) -> None:
        """prop_quant_agent, nba_quant_agent, prop_arbitrage_agent all in graph.nodes."""
        prop_arb_node = make_prop_arbitrage_agent(sport="nfl")
        graph = create_graph(
            checkpointer=MemorySaver(),
            prop_quant_node=_nfl_stub,
            nba_quant_node=_nba_stub,
            prop_arbitrage_node=prop_arb_node,
        )
        node_names = set(graph.nodes)
        assert "prop_quant_agent" in node_names, (
            f"'prop_quant_agent' not in graph.nodes: {node_names}"
        )
        assert "nba_quant_agent" in node_names, (
            f"'nba_quant_agent' not in graph.nodes: {node_names}"
        )
        assert "prop_arbitrage_agent" in node_names, (
            f"'prop_arbitrage_agent' not in graph.nodes: {node_names}"
        )


# ---------------------------------------------------------------------------
# Task 1 Tests — End-to-end pipeline (RED)
# ---------------------------------------------------------------------------

class TestE2EPropPipelineWiring:
    """End-to-end pipeline tests via graph.ainvoke."""

    def test_e2e_nfl_prop_pipeline(self) -> None:
        """NFL prop pipeline: ainvoke produces non-None ev_signal in single ainvoke."""
        prop_arb_node = make_prop_arbitrage_agent(sport="nfl")
        guard_node = make_correlation_guard_node()
        # Use large bankroll so Kelly fraction (6% of bankroll) stays under drawdown limit
        agg_node = make_aggregator_node(bankroll_usd=100_000.0, daily_drawdown_limit=0.10)
        graph = create_graph(
            checkpointer=MemorySaver(),
            prop_quant_node=_nfl_stub,
            nba_quant_node=_nba_stub,
            prop_arbitrage_node=prop_arb_node,
            correlation_guard_node=guard_node,
            aggregator_node=agg_node,
        )
        initial_state = _make_nfl_e2e_state()
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = asyncio.run(graph.ainvoke(initial_state, config=config))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, (
            f"E2E NFL prop pipeline produced None ev_signal. "
            f"prop_result={result.get('prop_result')}, "
            f"context_signals={result.get('context_signals')}"
        )

    def test_e2e_nba_prop_pipeline(self) -> None:
        """NBA prop pipeline: ainvoke with nba_prop_analysis produces non-None ev_signal."""
        prop_arb_node = make_prop_arbitrage_agent(sport="nba")
        guard_node = make_correlation_guard_node()
        agg_node = make_aggregator_node(bankroll_usd=100_000.0, daily_drawdown_limit=0.10)
        graph = create_graph(
            checkpointer=MemorySaver(),
            prop_quant_node=_nfl_stub,
            nba_quant_node=_nba_stub,
            prop_arbitrage_node=prop_arb_node,
            correlation_guard_node=guard_node,
            aggregator_node=agg_node,
        )
        initial_state = _make_nba_e2e_state()
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = asyncio.run(graph.ainvoke(initial_state, config=config))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, (
            f"E2E NBA prop pipeline produced None ev_signal. "
            f"nba_prop_result={result.get('nba_prop_result')}"
        )

    def test_prop_arbitrage_analysis_direct(self) -> None:
        """Direct prop_arbitrage_analysis route bypasses quant, produces non-None ev_signal."""
        prop_arb_node = make_prop_arbitrage_agent(sport="nfl")
        guard_node = make_correlation_guard_node()
        agg_node = make_aggregator_node(bankroll_usd=100_000.0, daily_drawdown_limit=0.10)
        graph = create_graph(
            checkpointer=MemorySaver(),
            prop_quant_node=_nfl_stub,
            nba_quant_node=_nba_stub,
            prop_arbitrage_node=prop_arb_node,
            correlation_guard_node=guard_node,
            aggregator_node=agg_node,
        )
        initial_state = _make_base_state(request_type="prop_arbitrage_analysis")
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = asyncio.run(graph.ainvoke(initial_state, config=config))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, (
            f"Direct prop_arbitrage_analysis route produced None ev_signal. "
            f"prop_result={result.get('prop_result')}"
        )
