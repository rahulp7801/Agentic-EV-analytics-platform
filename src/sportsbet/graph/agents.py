"""Stub agent nodes for the LangGraph state machine.

Each stub agent returns a hardcoded fixture instance of its typed output model,
storing it on GraphState. This establishes the interface contract that Phase 3+
agents will develop against — zero placeholder dicts, real Pydantic instances.

Phase replacement schedule (locked in CONTEXT.md):
- quant_agent  -> Phase 3: QuantParams validation + SQL query execution
- arbitrage_agent -> Phase 5: real odds comparison against Odds API
- context_agent   -> Phase 4: real context stream processing (X/Twitter, Reddit, RSS)

Design: stub agents return dicts (partial state updates), not full GraphState.
LangGraph merges the returned dict into the current state using registered reducers.
"""
from __future__ import annotations

from decimal import Decimal

import structlog

from sportsbet.graph.models import EVSignal, QuantResult
from sportsbet.graph.state import GraphState

log = structlog.get_logger()


def quant_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Quant Agent stub — returns a hardcoded QuantResult fixture instance.

    Stub: Phase 3 replaces this with QuantParams validation + SQL query.
    Fixture instance establishes interface contract for Phase 3 development.

    Returns a partial state dict with quant_result set to a QuantResult instance
    so callers can assert isinstance(result["quant_result"], QuantResult).
    """
    log.info("stub_agent_called", agent="quant_agent", session_id=state["session_id"])
    return {
        "quant_result": QuantResult(
            true_probability=Decimal("0.62"),
            sample_size=142,
            data_source="fixture",
        )
    }


def arbitrage_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Arbitrage Agent stub — returns a hardcoded EVSignal fixture instance.

    Stub: Phase 5 replaces this with real odds comparison logic.
    Fixture instance establishes interface contract for Phase 5 development.

    EVSignal fixture values:
    - ev_percentage=0.07  (7% edge over implied probability)
    - kelly_fraction=0.05 (5% fractional Kelly stake, well within 25% cap)
    - 2-item trade_plan (within CLAUDE.md 3-bullet limit)
    """
    log.info(
        "stub_agent_called", agent="arbitrage_agent", session_id=state["session_id"]
    )
    return {
        "ev_signal": EVSignal(
            ev_percentage=Decimal("0.07"),
            true_probability=Decimal("0.62"),
            implied_probability=Decimal("0.55"),
            kelly_fraction=Decimal("0.05"),
            trade_plan=["Fixture edge 1", "Fixture edge 2"],
            market_type="moneyline",
        )
    }


def context_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Context Agent stub — passthrough, no output model yet.

    Stub: Phase 4 replaces this with real context stream processing.
    Returns empty dict — no output model defined until Phase 4.
    """
    log.info(
        "stub_agent_called", agent="context_agent", session_id=state["session_id"]
    )
    return {}
