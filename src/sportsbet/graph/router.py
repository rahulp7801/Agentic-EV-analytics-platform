"""Validated request routing for the LangGraph state machine."""
from __future__ import annotations

import structlog

from sportsbet.graph.state import GraphState

log = structlog.get_logger()

ROUTE_TARGETS = {
    "quant_analysis": "quant_agent",
    "odds_check": "arbitrage_agent",
    "arbitrage_analysis": "arbitrage_agent",
    "context_update": "context_agent",
    "kinematic_analysis": "kinematic_agent",
    "prop_analysis": "prop_quant_agent",
    "nba_prop_analysis": "nba_quant_agent",
    "prop_arbitrage_analysis": "prop_arbitrage_agent",
    "market_analysis": "market_analysis",
}


def master_router(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Validate the route and clear stale signals whenever routing is blocked."""
    request_type = state.get("request_type")
    known_request = request_type in ROUTE_TARGETS
    log.info("master_router_called", session_id=state["session_id"],
             request_type=request_type if known_request else "unknown",
             has_error=state.get("error") is not None)
    if state.get("error") is not None:
        return {"ev_signal": None, "pending_signals": [], "cleared_signals": [],
                "gate_reason": "model_error"}
    if not known_request:
        return {"request_type": "unknown", "error": "unknown_request_type", "ev_signal": None,
                "pending_signals": [], "cleared_signals": [], "gate_reason": "model_error"}
    return {}


def route_from_master(state: GraphState) -> str:
    """Return a validated node name, or terminate a state that already has an error."""
    if state.get("error") is not None:
        log.warning("master_router_short_circuit", reason="state_error",
                    session_id=state["session_id"])
        return "end"
    return ROUTE_TARGETS[state["request_type"]]
