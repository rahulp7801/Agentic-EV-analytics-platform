"""LangGraph StateGraph factory for the sportsbet agent pipeline.

create_graph() builds and compiles the full directed graph:

  START -> master_router -> [conditional edge] -> quant_agent   -> END
                                               -> arbitrage_agent -> END
                                               -> context_agent   -> END
                                               -> END  (on error or unknown type)

No checkpointer is attached in Phase 2 — Plan 02-03 adds AsyncPostgresSaver.
Downstream phases (3, 4, 5, 6) import create_graph() and replace stub agent
nodes with real implementations.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sportsbet.graph.agents import arbitrage_agent, context_agent, quant_agent
from sportsbet.graph.router import master_router, route_from_master
from sportsbet.graph.state import GraphState


def create_graph() -> CompiledStateGraph:
    """Build and compile the LangGraph StateGraph for the sportsbet agent pipeline.

    Graph topology (Phase 2 stub wiring):
    - Entry point: master_router
    - Conditional edges from master_router dispatch to specialist stubs
    - Each specialist stub terminates at END after setting its output on state

    Returns
    -------
    CompiledStateGraph
        Ready for ainvoke(initial_state) calls. Thread-safe: each ainvoke
        gets its own isolated state copy.
    """
    builder: StateGraph = StateGraph(GraphState)

    # Register all nodes
    builder.add_node("master_router", master_router)
    builder.add_node("quant_agent", quant_agent)
    builder.add_node("arbitrage_agent", arbitrage_agent)
    builder.add_node("context_agent", context_agent)

    # Entry point: all requests pass through master_router first
    builder.set_entry_point("master_router")

    # Conditional dispatch from master_router based on request_type / error
    builder.add_conditional_edges(
        "master_router",
        route_from_master,
        {
            "quant_agent": "quant_agent",
            "arbitrage_agent": "arbitrage_agent",
            "context_agent": "context_agent",
            "end": END,
        },
    )

    # All specialist stubs terminate immediately after running
    builder.add_edge("quant_agent", END)
    builder.add_edge("arbitrage_agent", END)
    builder.add_edge("context_agent", END)

    # Compile without checkpointer — Plan 02-03 adds AsyncPostgresSaver
    return builder.compile()
