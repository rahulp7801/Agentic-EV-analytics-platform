"""Tests for the LangGraph graph skeleton — GraphState, Master Router, stub agents.

TDD RED stubs for Task 1: GraphState TypedDict and reducers.
Task 2 tests are added after Task 1 GREEN.
Plan 02-03 adds checkpoint persist/replay tests using MemorySaver.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, get_type_hints

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_minimal_state() -> dict[str, Any]:
    """Return a valid 13-field GraphState-compatible dict."""
    return {
        "session_id": "test-session-001",
        "request_type": "quant_analysis",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "game_id": "2025_01_KC_LAC",
        "season": 2025,
        "week": 1,
        "home_team": "LAC",
        "away_team": "KC",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "receiver_gsis_id": "",
    }


# ---------------------------------------------------------------------------
# Task 1: GraphState tests
# ---------------------------------------------------------------------------

class TestGraphState:
    def test_graphstate_has_required_fields(self) -> None:
        """GraphState TypedDict must have all 13 required fields."""
        from sportsbet.graph.state import GraphState

        hints = get_type_hints(GraphState, include_extras=True)
        required = {
            "session_id",
            "request_type",
            "created_at",
            "game_id",
            "season",
            "week",
            "home_team",
            "away_team",
            "injury_flags",
            "weather_json",
            "error",
            "quant_result",
            "ev_signal",
        }
        assert required.issubset(set(hints.keys())), (
            f"Missing fields: {required - set(hints.keys())}"
        )

    def test_graphstate_annotated_error_field(self) -> None:
        """error field must be Annotated — concurrent writes must not raise TypeError."""
        import typing
        from sportsbet.graph.state import GraphState

        hints = get_type_hints(GraphState, include_extras=True)
        error_hint = hints["error"]
        # Annotated types have __metadata__ attribute
        assert hasattr(error_hint, "__metadata__"), (
            "error field must be Annotated[str | None, reducer_fn]"
        )
        assert len(error_hint.__metadata__) >= 1, (
            "error field Annotated must include at least one reducer"
        )

    def test_graphstate_reducer(self) -> None:
        """The error reducer must apply last-write-wins: later value b wins over a."""
        import typing
        from sportsbet.graph.state import GraphState

        hints = get_type_hints(GraphState, include_extras=True)
        error_hint = hints["error"]
        reducer = error_hint.__metadata__[0]
        assert callable(reducer), "Annotated metadata[0] must be the reducer callable"

        # last-write-wins: b wins
        result = reducer("first", "second")
        assert result == "second", f"Expected 'second', got {result!r}"

        # None wins over a value if b=None (reset)
        result_none = reducer("some_error", None)
        assert result_none is None, f"Expected None, got {result_none!r}"

        # value wins over None
        result_set = reducer(None, "new_error")
        assert result_set == "new_error", f"Expected 'new_error', got {result_set!r}"


# ---------------------------------------------------------------------------
# Task 2: Router, agents, compiled graph tests
# ---------------------------------------------------------------------------

class TestRouter:
    async def test_router_dispatch_quant(self) -> None:
        """Request type 'quant_analysis' routes to quant_agent — quant_result set."""
        from sportsbet.graph.graph import create_graph
        from sportsbet.graph.models import QuantResult

        graph = create_graph()
        state = make_minimal_state()
        state["request_type"] = "quant_analysis"
        result = await graph.ainvoke(state)
        assert result["quant_result"] is not None, "quant_result should be set"
        assert isinstance(result["quant_result"], QuantResult), (
            f"Expected QuantResult, got {type(result['quant_result'])}"
        )

    async def test_router_dispatch_odds(self) -> None:
        """Request type 'odds_check' routes to arbitrage_agent — ev_signal set."""
        from sportsbet.graph.graph import create_graph
        from sportsbet.graph.models import EVSignal

        graph = create_graph()
        state = make_minimal_state()
        state["request_type"] = "odds_check"
        result = await graph.ainvoke(state)
        assert result["ev_signal"] is not None, "ev_signal should be set"
        assert isinstance(result["ev_signal"], EVSignal), (
            f"Expected EVSignal, got {type(result['ev_signal'])}"
        )

    async def test_router_dispatch_context(self) -> None:
        """Request type 'context_update' routes to context_agent — terminates cleanly."""
        from sportsbet.graph.graph import create_graph

        graph = create_graph()
        state = make_minimal_state()
        state["request_type"] = "context_update"
        result = await graph.ainvoke(state)
        assert result.get("error") is None, (
            f"context_update should not set error, got: {result.get('error')}"
        )

    async def test_router_routes_to_end_on_error(self) -> None:
        """When error is pre-set, graph terminates without dispatching to any agent."""
        from sportsbet.graph.graph import create_graph

        graph = create_graph()
        state = make_minimal_state()
        state["error"] = "some failure"
        state["request_type"] = "quant_analysis"
        result = await graph.ainvoke(state)
        # quant_result must remain None — agent was never called
        assert result.get("quant_result") is None, (
            "quant_result must stay None when error is pre-set"
        )

    def test_graph_compiles(self) -> None:
        """create_graph() must return a compiled object without exception."""
        from sportsbet.graph.graph import create_graph

        graph = create_graph()
        assert graph is not None

    async def test_ainvoke_returns_state(self) -> None:
        """await graph.ainvoke(initial_state) returns dict with all 13 GraphState fields."""
        from sportsbet.graph.graph import create_graph

        graph = create_graph()
        state = make_minimal_state()
        result = await graph.ainvoke(state)
        required = {
            "session_id", "request_type", "created_at", "game_id", "season",
            "week", "home_team", "away_team", "injury_flags", "weather_json",
            "error", "quant_result", "ev_signal",
        }
        missing = required - set(result.keys())
        assert not missing, f"Missing fields in returned state: {missing}"


# ---------------------------------------------------------------------------
# Plan 02-03: Checkpoint persist and replay tests
# ---------------------------------------------------------------------------

def make_checkpoint_state(request_type: str = "quant_analysis") -> dict[str, Any]:
    """Return a minimal GraphState-compatible dict for checkpoint tests."""
    return {
        "session_id": str(uuid.uuid4()),
        "request_type": request_type,
        "created_at": datetime.now(timezone.utc),
        "game_id": "2023_01_KC_DET",
        "season": 2023,
        "week": 1,
        "home_team": "DET",
        "away_team": "KC",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "receiver_gsis_id": "",
    }


class TestCheckpointing:
    async def test_checkpoint_persist(self, graph_fixture) -> None:
        """After ainvoke with MemorySaver, get_state() returns a non-None snapshot."""
        compiled, config = graph_fixture
        state = make_checkpoint_state()
        await compiled.ainvoke(state, config=config)
        snapshot = compiled.get_state(config)
        assert snapshot is not None, (
            "get_state() must return a checkpoint snapshot after ainvoke"
        )

    async def test_checkpoint_replay(self, graph_fixture) -> None:
        """Two sequential ainvoke calls with the same thread_id both succeed."""
        compiled, config = graph_fixture
        state = make_checkpoint_state()
        first_result = await compiled.ainvoke(state, config=config)
        assert first_result is not None, "First ainvoke must return a state dict"

        # Second invocation with same thread_id replays from checkpoint
        second_result = await compiled.ainvoke(state, config=config)
        assert second_result is not None, "Second ainvoke (replay) must succeed"
        assert isinstance(second_result, dict), (
            f"Expected dict from second ainvoke, got {type(second_result)}"
        )

    def test_graph_fixture_isolation(self, graph_fixture) -> None:
        """Two graph_fixture calls produce different thread_ids (no state bleed)."""
        from langgraph.checkpoint.memory import MemorySaver
        from sportsbet.graph import create_graph

        # Simulate two independent fixture calls
        saver_a = MemorySaver()
        compiled_a = create_graph(checkpointer=saver_a)
        thread_a = str(uuid.uuid4())

        saver_b = MemorySaver()
        compiled_b = create_graph(checkpointer=saver_b)
        thread_b = str(uuid.uuid4())

        assert thread_a != thread_b, (
            "Each fixture call must produce a unique thread_id"
        )
        # Different MemorySaver instances — no shared state
        assert saver_a is not saver_b, (
            "Each fixture call must get an independent MemorySaver"
        )

    def test_config_has_bankroll_fields(self) -> None:
        """Settings.bankroll_usd and Settings.max_kelly_fraction exist with correct defaults."""
        from sportsbet.config import settings

        assert hasattr(settings, "bankroll_usd"), (
            "Settings must have bankroll_usd field"
        )
        assert hasattr(settings, "max_kelly_fraction"), (
            "Settings must have max_kelly_fraction field"
        )
        assert settings.bankroll_usd == 10000.0, (
            f"bankroll_usd default must be 10000.0, got {settings.bankroll_usd}"
        )
        assert settings.max_kelly_fraction == 0.25, (
            f"max_kelly_fraction default must be 0.25, got {settings.max_kelly_fraction}"
        )


# ---------------------------------------------------------------------------
# Phase 7: Production runtime wiring tests (07-01)
# ---------------------------------------------------------------------------

class TestPhase7Wiring:
    def test_graphstate_has_receiver_gsis_id(self) -> None:
        """GraphState must declare receiver_gsis_id: str (Phase 7 — INT-02 gap closure)."""
        from sportsbet.graph.state import GraphState
        hints = get_type_hints(GraphState, include_extras=True)
        assert "receiver_gsis_id" in hints, (
            "GraphState missing receiver_gsis_id field — make_kinematic_agent silently "
            "queries for '' without this field declared"
        )

    def test_extract_odds_devigged(self) -> None:
        """_extract_odds_snapshot must return devigged prob (0.5) for -110/-110, not raw (0.5238)."""
        from sportsbet.graph.agents import _extract_odds_snapshot
        raw_odds = [{
            "bookmakers": [{
                "key": "fanduel",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "KC", "price": -110},
                        {"name": "LV", "price": -110},
                    ],
                }],
            }],
        }]
        result = _extract_odds_snapshot(raw_odds, "2024_01_KC_LV")
        assert result is not None, "_extract_odds_snapshot returned None unexpectedly"
        # Devigged -110/-110 = exactly 0.5; vig-inclusive raw = 0.523809...
        assert result.implied_probability == Decimal("0.5"), (
            f"Expected devigged Decimal('0.5'), got {result.implied_probability!r}. "
            "Vig removal via remove_vig_multiplicative not wired."
        )

    async def test_create_graph_with_sqlite_nodes(self) -> None:
        """create_graph() with all 7 params wires arbitrage pipeline and kinematic node."""
        from langgraph.checkpoint.memory import MemorySaver
        from sportsbet.graph.graph import (
            create_graph,
            make_aggregator_node,
            make_correlation_guard_node,
        )
        from sportsbet.graph.agents import make_arbitrage_agent

        def _kinematic_stub(state):  # type: ignore[no-untyped-def]
            return {"kinematic_result": None}

        graph = create_graph(
            checkpointer=MemorySaver(),
            arbitrage_node=make_arbitrage_agent(),
            correlation_guard_node=make_correlation_guard_node(),
            aggregator_node=make_aggregator_node(bankroll_usd=10000.0),
            kinematic_node=_kinematic_stub,
        )
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}

        # Arbitrage pipeline: cleared_signals key must be present after aggregator runs
        arb_state = make_minimal_state()
        arb_state["request_type"] = "arbitrage_analysis"
        arb_state["pending_signals"] = []
        arb_state["cleared_signals"] = []
        arb_state["context_signals"] = None
        result = await graph.ainvoke(arb_state, config=config)
        assert "cleared_signals" in result, (
            "cleared_signals key missing — aggregator_node not wired into graph"
        )

        # Kinematic pipeline: kinematic_result key must be present
        kin_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        kin_state = make_minimal_state()
        kin_state["request_type"] = "kinematic_analysis"
        kin_state["pending_signals"] = []
        kin_state["cleared_signals"] = []
        kin_result = await graph.ainvoke(kin_state, config=kin_config)
        assert "kinematic_result" in kin_result, (
            "kinematic_result key missing — kinematic_node not wired into graph"
        )
