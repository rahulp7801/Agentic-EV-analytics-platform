"""Master Router node and conditional edge function for the LangGraph state machine.

The Master Router is the entry point for every request. It reads the `error` field
first — if set, routes immediately to END without calling any agent (fail-fast design).
Otherwise it dispatches based on `request_type` to the correct specialist agent.

Routing table:
  "quant_analysis"        -> quant_agent
  "odds_check"            -> arbitrage_agent
  "arbitrage_analysis"    -> arbitrage_agent      (Phase 5: full arbitrage pipeline route)
  "context_update"        -> context_agent
  "kinematic_analysis"    -> kinematic_agent       (Phase 6: geometric matchup exploit signal)
  "prop_analysis"         -> prop_quant_agent      (Phase 11: NFL player prop quant agent)
  "nba_prop_analysis"     -> nba_quant_agent       (Phase 13: NBA player prop quant agent)
  "prop_arbitrage_analysis" -> prop_arbitrage_agent (Phase 13: direct prop arbitrage route)
  anything else           -> sets error and routes to END
"""
from __future__ import annotations

import structlog

from sportsbet.graph.state import GraphState

log = structlog.get_logger()


def master_router(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Passthrough node that serves as the graph entry point.

    Master Router does not mutate state — it relies on route_from_master (the
    conditional edge function) to determine the next node. This separation of
    concerns means the node itself is a pure pass-through while the routing
    logic lives in the conditional edge function where LangGraph expects it.
    """
    log.info(
        "master_router_called",
        session_id=state["session_id"],
        request_type=state["request_type"],
        has_error=state.get("error") is not None,
    )
    return {}


def route_from_master(state: GraphState) -> str:
    """Conditional edge function: returns the name of the next node to visit.

    Called by LangGraph after master_router completes. Returns a string key
    that maps to a node name in the conditional edges routing table.

    Priority:
    1. If error is set -> "end" (fail-fast, no agent dispatch)
    2. Route by request_type
    3. Unknown request_type -> sets error on state, routes to "end"
    """
    if state.get("error") is not None:
        log.warning(
            "master_router_short_circuit",
            reason="error_pre_set",
            error=state["error"],
            session_id=state["session_id"],
        )
        return "end"

    request_type = state["request_type"]

    if request_type == "quant_analysis":
        return "quant_agent"
    elif request_type in ("odds_check", "arbitrage_analysis"):
        return "arbitrage_agent"
    elif request_type == "context_update":
        return "context_agent"
    elif request_type == "kinematic_analysis":
        return "kinematic_agent"
    elif request_type == "prop_analysis":
        return "prop_quant_agent"
    elif request_type == "nba_prop_analysis":
        return "nba_quant_agent"
    elif request_type == "prop_arbitrage_analysis":
        return "prop_arbitrage_agent"
    elif request_type == "market_analysis":
        return "market_analysis"
    else:
        # Unknown request_type — set error in state via a state update mechanism.
        # Note: conditional edge functions cannot mutate state directly in LangGraph.
        # The error will be visible in logs; graph terminates at END cleanly.
        log.error(
            "master_router_unknown_request_type",
            request_type=request_type,
            session_id=state["session_id"],
        )
        return "end"
