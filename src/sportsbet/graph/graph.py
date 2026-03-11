"""LangGraph StateGraph factory for the sportsbet agent pipeline.

create_graph() builds and compiles the full directed graph:

  START -> master_router -> [conditional edge] -> quant_agent   -> END
                                               -> arbitrage_agent -> END
                                               -> context_agent   -> END
                                               -> END  (on error or unknown type)

create_graph_with_sqlite() is the runtime factory — writes checkpoints to disk
at .checkpoints/sportsbet.sqlite using sync SqliteSaver.

All tests use create_graph(checkpointer=MemorySaver()) for full isolation (no disk I/O).
Downstream phases (3, 4, 5, 6) import create_graph() and replace stub agent
nodes with real implementations.
"""
from __future__ import annotations

import os
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sportsbet.graph.agents import arbitrage_agent, context_agent, quant_agent
from sportsbet.graph.router import master_router, route_from_master
from sportsbet.graph.state import GraphState


def create_graph(checkpointer: Any = None) -> CompiledStateGraph:
    """Build and compile the LangGraph StateGraph for the sportsbet agent pipeline.

    Graph topology (Phase 2 stub wiring):
    - Entry point: master_router
    - Conditional edges from master_router dispatch to specialist stubs
    - Each specialist stub terminates at END after setting its output on state

    Parameters
    ----------
    checkpointer:
        Optional LangGraph checkpointer (e.g. MemorySaver for tests,
        SqliteSaver for runtime). If None, compiles without checkpointing
        (backward-compatible with Plan 02-02 tests).

    Returns
    -------
    CompiledStateGraph
        Ready for ainvoke(initial_state, config={"configurable": {"thread_id": ...}}) calls.
        Thread-safe: each ainvoke gets its own isolated state copy.
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

    return builder.compile(checkpointer=checkpointer)


async def create_graph_with_sqlite(
    db_path: str = ".checkpoints/sportsbet.sqlite",
) -> CompiledStateGraph:
    """Build and compile the graph with an AsyncSqliteSaver checkpointer for runtime use.

    Creates the .checkpoints/ directory if it does not exist, then instantiates
    an AsyncSqliteSaver and passes it to create_graph().

    Must be called from within an async context (use asyncio.run() from sync code).
    Do NOT use in tests — use create_graph(checkpointer=MemorySaver()) instead
    to avoid disk I/O and cleanup overhead.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file for checkpoint storage.
        Defaults to .checkpoints/sportsbet.sqlite (relative to cwd).

    Returns
    -------
    CompiledStateGraph
        Graph compiled with AsyncSqliteSaver. Pass thread_id via
        config={"configurable": {"thread_id": "..."}} on ainvoke to enable
        checkpoint persistence and replay.

    Notes
    -----
    The returned graph holds an open aiosqlite connection. The connection
    remains open for the lifetime of the graph; for production use wrap in
    an async context manager or ensure the process lifecycle closes it.
    """
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    # Open a persistent aiosqlite connection for the graph's lifetime.
    conn = await aiosqlite.connect(db_path)
    saver = AsyncSqliteSaver(conn)
    return create_graph(checkpointer=saver)
