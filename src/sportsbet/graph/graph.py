"""LangGraph StateGraph factory for the sportsbet agent pipeline.

create_graph() builds and compiles the full directed graph:

  START -> master_router -> [conditional edge] -> quant_agent          -> END
                                               -> arbitrage_agent       -> [correlation_guard -> aggregator ->] END
                                               -> context_agent         -> END
                                               -> kinematic_agent       -> END
                                               -> prop_quant_agent      -> prop_arbitrage_agent -> [correlation_guard -> aggregator ->] END
                                               -> nba_quant_agent       -> prop_arbitrage_agent -> [correlation_guard -> aggregator ->] END
                                               -> prop_arbitrage_agent  -> [correlation_guard -> aggregator ->] END
                                               -> END  (on error or unknown type)

create_graph_with_sqlite() is the runtime factory — writes checkpoints to disk
at .checkpoints/sportsbet.sqlite using AsyncSqliteSaver.

Phase 3 Plan 01 update: create_graph() accepts an optional quant_node parameter.
- If quant_node is None (default): uses the sync stub quant_agent (Phase 2 backward-compat).
- If quant_node is provided: uses the real async closure from make_quant_agent(pool).

Phase 4 Plan 04 update: create_graph() accepts an optional context_node parameter.
- If context_node is None (default): uses the sync stub context_agent (Phase 2 backward-compat).
- If context_node is provided: uses the real async closure from make_context_agent(pool, api_key, cap).

Phase 5 Plan 03 update: create_graph() accepts optional arbitrage_node, correlation_guard_node,
and aggregator_node parameters.
- arbitrage_node: real async closure from make_arbitrage_agent(); None uses sync stub.
- correlation_guard_node: from make_correlation_guard_node(); None skips guard.
- aggregator_node: from make_aggregator_node(bankroll, limit); None skips gate.
When correlation_guard_node and aggregator_node are both provided, the arbitrage pipeline
is extended: arbitrage_agent -> correlation_guard -> aggregator -> END.

Phase 6 Plan 02 update: create_graph() accepts an optional kinematic_node parameter.
- If kinematic_node is None (default): uses _kinematic_stub (returns kinematic_result=None).
- If kinematic_node is provided: uses the real async closure from make_kinematic_agent(pool).

Phase 13 Plan 02 update: create_graph() accepts optional prop_quant_node, nba_quant_node,
and prop_arbitrage_node parameters.
- prop_quant_node: real async closure from make_prop_quant_agent(pool); None uses _prop_quant_stub.
- nba_quant_node: real async closure from make_nba_quant_agent(pool); None uses _nba_quant_stub.
- prop_arbitrage_node: real async closure from make_prop_arbitrage_agent(sport); None uses _prop_arb_stub.
Both prop_quant_agent and nba_quant_agent chain to the same prop_arbitrage_agent node.
prop_arbitrage_agent chains to correlation_guard (if present) or directly to END.
create_graph_with_sqlite() wires all three when pool is provided.

All tests use create_graph(checkpointer=MemorySaver()) for full isolation (no disk I/O).
Tests requiring a real quant agent pass quant_node=make_quant_agent(pool) explicitly.
Tests requiring a real context agent pass context_node=make_context_agent(pool, key, cap) explicitly.
Tests requiring full arbitrage pipeline pass all three new node parameters explicitly.
Tests requiring real kinematic agent pass kinematic_node=make_kinematic_agent(pool) explicitly.
Tests requiring real prop agents pass prop_quant_node, nba_quant_node, prop_arbitrage_node explicitly.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sportsbet.graph.agents import arbitrage_agent, context_agent, quant_agent
from sportsbet.graph.router import master_router, route_from_master
from sportsbet.graph.state import GraphState


# ---------------------------------------------------------------------------
# Graph-layer node factories for Phase 5 risk controls
# ---------------------------------------------------------------------------


def make_correlation_guard_node() -> Callable[[GraphState], dict]:  # type: ignore[type-arg]
    """Return a sync LangGraph node that applies CorrelationGuard.check().

    Reads pending_signals from state, filters conflicting pairs, writes
    result back to pending_signals (overwrite — cleared signals ready for Aggregator).

    The CorrelationGuard instance is stateless — safe to share across invocations.
    """
    from sportsbet.arbitrage.correlation_guard import CorrelationGuard
    guard = CorrelationGuard()

    def correlation_guard_node(state: GraphState) -> dict:  # type: ignore[type-arg]
        raw = state.get("pending_signals") or []  # type: ignore[attr-defined]
        cleared = guard.check(raw)
        return {"pending_signals": cleared}

    return correlation_guard_node


def make_aggregator_node(
    bankroll_usd: float,
    daily_drawdown_limit: float = 0.05,
) -> Callable[[GraphState], dict]:  # type: ignore[type-arg]
    """Return a sync LangGraph node that applies the Aggregator daily drawdown gate.

    The Aggregator instance is created once at graph construction time —
    it persists cumulative_exposure_usd across multiple graph invocations
    within the same process lifetime. This simulates the daily gate.

    Reads pending_signals (already CorrelationGuard-filtered), calls
    record_signal() for each, writes accepted signals to cleared_signals.
    Sets ev_signal to the first cleared signal (or None if none pass).

    Parameters
    ----------
    bankroll_usd:
        Total bankroll in USD used to calculate daily exposure limit.
    daily_drawdown_limit:
        Fraction of bankroll as maximum daily exposure (default 0.05 = 5%).
    """
    from sportsbet.arbitrage.aggregator import Aggregator
    agg = Aggregator(bankroll_usd=bankroll_usd, daily_drawdown_limit=daily_drawdown_limit)

    def aggregator_node(state: GraphState) -> dict:  # type: ignore[type-arg]
        candidates = state.get("pending_signals") or []  # type: ignore[attr-defined]
        cleared = []
        for sig in candidates:
            if agg.record_signal(sig):
                cleared.append(sig)
        return {
            "cleared_signals": cleared,
            "ev_signal": cleared[0] if cleared else None,
        }

    return aggregator_node


def create_graph(
    checkpointer: Any = None,
    quant_node: Any = None,
    context_node: Any = None,
    arbitrage_node: Any = None,
    correlation_guard_node: Any = None,
    aggregator_node: Any = None,
    kinematic_node: Any = None,
    prop_quant_node: Any = None,
    nba_quant_node: Any = None,
    prop_arbitrage_node: Any = None,
) -> CompiledStateGraph:
    """Build and compile the LangGraph StateGraph for the sportsbet agent pipeline.

    Graph topology (base):
    - Entry point: master_router
    - Conditional edges from master_router dispatch to specialist agents
    - Each specialist agent terminates at END after setting its output on state

    Graph topology (with full arbitrage pipeline):
    - arbitrage_agent -> correlation_guard -> aggregator -> END
      (only when correlation_guard_node and aggregator_node are both provided)

    Parameters
    ----------
    checkpointer:
        Optional LangGraph checkpointer (e.g. MemorySaver for tests,
        AsyncSqliteSaver for runtime). If None, compiles without checkpointing
        (backward-compatible with Plan 02-02 tests).
    quant_node:
        Optional async quant agent node. If None, uses the sync stub quant_agent
        (Phase 2 backward-compat). Pass make_quant_agent(pool) for real SQL execution.
    context_node:
        Optional async context agent node. If None, uses the sync stub context_agent
        (Phase 2 backward-compat). Pass make_context_agent(pool, api_key, cap) for
        real odds + injury pipeline execution.
    arbitrage_node:
        Optional async arbitrage agent node. If None, uses the sync stub arbitrage_agent
        (Phase 2 backward-compat). Pass make_arbitrage_agent() for real EV computation.
    correlation_guard_node:
        Optional sync node from make_correlation_guard_node(). When provided alongside
        aggregator_node, extends the arbitrage pipeline with CorrelationGuard filtering.
        If None, arbitrage_agent routes directly to END (backward-compat).
    aggregator_node:
        Optional sync node from make_aggregator_node(bankroll, limit). When provided
        alongside correlation_guard_node, gates signals through the daily drawdown limit.
        If None, arbitrage_agent routes directly to END (backward-compat).
    kinematic_node:
        Optional async kinematic agent node. If None, uses _kinematic_stub which returns
        {"kinematic_result": None} (backward-compat). Pass make_kinematic_agent(pool) for
        real NGS separation query execution.
    prop_quant_node:
        Optional async NFL prop quant agent node. If None, uses _prop_quant_stub which
        returns {"prop_result": None}. Pass make_prop_quant_agent(pool) for real SQL.
        Chains to prop_arbitrage_agent after execution.
    nba_quant_node:
        Optional async NBA prop quant agent node. If None, uses _nba_quant_stub which
        returns {"nba_prop_result": None}. Pass make_nba_quant_agent(pool) for real SQL.
        Chains to prop_arbitrage_agent after execution.
    prop_arbitrage_node:
        Optional async prop arbitrage agent node. If None, uses _prop_arb_stub which
        returns {"ev_signal": None}. Pass make_prop_arbitrage_agent(sport) for real EV.
        Receives output from prop_quant_agent, nba_quant_agent, or directly from router.
        Chains to correlation_guard (if present) or END.

    Returns
    -------
    CompiledStateGraph
        Ready for ainvoke(initial_state, config={"configurable": {"thread_id": ...}}) calls.
        Thread-safe: each ainvoke gets its own isolated state copy.
    """
    from sportsbet.graph.router import route_from_master

    builder: StateGraph = StateGraph(GraphState)

    # quant_node: real async closure (Phase 3+) or sync stub (Phase 2 backward-compat)
    active_quant_node = quant_node if quant_node is not None else quant_agent

    # context_node: real async closure (Phase 4+) or sync stub (Phase 2 backward-compat)
    active_context_node = context_node if context_node is not None else context_agent

    # arbitrage_node: real async closure (Phase 5+) or sync stub (Phase 2 backward-compat)
    active_arbitrage_node = arbitrage_node if arbitrage_node is not None else arbitrage_agent

    # kinematic_node: real async closure (Phase 6+) or inline stub (backward-compat)
    def _kinematic_stub(state: GraphState) -> dict:  # type: ignore[type-arg]
        """Inline stub: returns kinematic_result=None when no real kinematic node provided."""
        return {"kinematic_result": None}

    active_kinematic_node = kinematic_node if kinematic_node is not None else _kinematic_stub

    # prop_quant_node: real async closure (Phase 13+) or inline stub (backward-compat)
    def _prop_quant_stub(state: GraphState) -> dict:  # type: ignore[type-arg]
        """Inline stub: returns prop_result=None when no real prop quant node provided."""
        return {"prop_result": None}

    # nba_quant_node: real async closure (Phase 13+) or inline stub (backward-compat)
    def _nba_quant_stub(state: GraphState) -> dict:  # type: ignore[type-arg]
        """Inline stub: returns nba_prop_result=None when no real NBA quant node provided."""
        return {"nba_prop_result": None}

    # prop_arbitrage_node: real async closure (Phase 13+) or inline stub (backward-compat)
    def _prop_arb_stub(state: GraphState) -> dict:  # type: ignore[type-arg]
        """Inline stub: returns ev_signal=None when no real prop arbitrage node provided."""
        return {"ev_signal": None}

    active_prop_quant_node = prop_quant_node if prop_quant_node is not None else _prop_quant_stub
    active_nba_quant_node = nba_quant_node if nba_quant_node is not None else _nba_quant_stub
    active_prop_arbitrage_node = prop_arbitrage_node if prop_arbitrage_node is not None else _prop_arb_stub

    # Register all base nodes
    builder.add_node("master_router", master_router)
    builder.add_node("quant_agent", active_quant_node)
    builder.add_node("arbitrage_agent", active_arbitrage_node)
    builder.add_node("context_agent", active_context_node)
    builder.add_node("kinematic_agent", active_kinematic_node)

    # Register Phase 13 prop pipeline nodes
    builder.add_node("prop_quant_agent", active_prop_quant_node)
    builder.add_node("nba_quant_agent", active_nba_quant_node)
    builder.add_node("prop_arbitrage_agent", active_prop_arbitrage_node)

    # Entry point: all requests pass through master_router first
    builder.set_entry_point("master_router")

    # Conditional dispatch from master_router based on request_type / error
    builder.add_conditional_edges(
        "master_router",
        route_from_master,
        {
            "quant_agent": "quant_agent",
            "arbitrage_agent": "arbitrage_agent",
            "arbitrage_analysis": "arbitrage_agent",
            "context_agent": "context_agent",
            "kinematic_agent": "kinematic_agent",
            "prop_quant_agent": "prop_quant_agent",
            "nba_quant_agent": "nba_quant_agent",
            "prop_arbitrage_agent": "prop_arbitrage_agent",
            "end": END,
        },
    )

    # quant_agent and context_agent always terminate at END
    builder.add_edge("quant_agent", END)
    builder.add_edge("context_agent", END)

    # kinematic_agent always terminates at END (independent pipeline)
    builder.add_edge("kinematic_agent", END)

    # PROP-04 kinematic boost: two-invocation checkpoint pattern (GAP-INT-2).
    # To incorporate kinematic separation/press-man signals into NFL receiving prop estimates:
    #   Invocation 1: ainvoke({"request_type": "kinematic_analysis", ...},
    #                          config={"configurable": {"thread_id": tid}})
    #                 -> kinematic_agent writes KinematicAnalysis to state["kinematic_result"]
    #                 -> AsyncSqliteSaver persists it in the checkpoint under thread_id
    #   Invocation 2: ainvoke({"request_type": "prop_analysis", ...},
    #                          config={"configurable": {"thread_id": tid}})
    #                 -> prop_quant_agent reads state.get("kinematic_result") from checkpoint
    #                 -> _apply_kinematic_adjustment() boosts probability if RECEIVING_PROPS match
    # Both invocations MUST use the same thread_id. Single-invocation path not supported.

    # Both prop quant agents chain to the same prop_arbitrage_agent (single ainvoke)
    builder.add_edge("prop_quant_agent", "prop_arbitrage_agent")
    builder.add_edge("nba_quant_agent", "prop_arbitrage_agent")

    # arbitrage pipeline: extend with guard/gate when both are provided
    if correlation_guard_node is not None and aggregator_node is not None:
        builder.add_node("correlation_guard", correlation_guard_node)
        builder.add_node("aggregator", aggregator_node)
        builder.add_edge("arbitrage_agent", "correlation_guard")
        builder.add_edge("correlation_guard", "aggregator")
        builder.add_edge("aggregator", END)
        # prop_arbitrage_agent reuses the same correlation_guard -> aggregator chain
        builder.add_edge("prop_arbitrage_agent", "correlation_guard")
    else:
        # Backward-compat: no risk controls, agents route directly to END
        builder.add_edge("arbitrage_agent", END)
        builder.add_edge("prop_arbitrage_agent", END)

    return builder.compile(checkpointer=checkpointer)


async def create_graph_with_sqlite(
    db_path: str = ".checkpoints/sportsbet.sqlite",
    pool: Any = None,
    api_key: str | None = None,
    daily_credit_cap: int = 500,
    bankroll_usd: float = 10000.0,
    daily_drawdown_limit: float = 0.05,
) -> CompiledStateGraph:
    """Build and compile the graph with an AsyncSqliteSaver checkpointer for runtime use.

    Creates the .checkpoints/ directory if it does not exist, then instantiates
    an AsyncSqliteSaver and passes it to create_graph().

    Phase 3 Plan 01 update: accepts an optional asyncpg pool. If provided,
    wires in make_quant_agent(pool) for real SQL execution.

    Phase 4 Plan 04 update: accepts optional api_key and daily_credit_cap.
    If pool is provided AND api_key is provided, wires in make_context_agent(pool,
    api_key, daily_credit_cap) for real odds + injury pipeline execution.

    Phase 7 update: accepts bankroll_usd and daily_drawdown_limit. Wires
    make_arbitrage_agent(), make_correlation_guard_node(), make_aggregator_node(),
    and make_kinematic_agent(pool) into create_graph() — all Phase 5/6 nodes are
    now reachable via the production factory (closes INT-01).

    Phase 13 Plan 02 update: wires make_prop_quant_agent(pool), make_nba_quant_agent(pool),
    and make_prop_arbitrage_agent(sport='nfl') when pool is provided. All three prop
    pipeline nodes are gated on pool availability (same as quant/kinematic nodes).

    Must be called from within an async context (use asyncio.run() from sync code).
    Do NOT use in tests — use create_graph(checkpointer=MemorySaver()) instead
    to avoid disk I/O and cleanup overhead.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file for checkpoint storage.
        Defaults to .checkpoints/sportsbet.sqlite (relative to cwd).
    pool:
        Optional asyncpg.Pool. If provided, wires real quant agent into graph.
        If None, uses sync stub (backward-compat).
    api_key:
        Optional Odds API key. If provided alongside pool, wires real context
        agent into graph. If None, uses sync stub (backward-compat).
    daily_credit_cap:
        Maximum Odds API credits allowed per day. Passed to make_context_agent.
        Defaults to 500.
    bankroll_usd:
        Total bankroll in USD for Aggregator daily drawdown gate. Defaults to 10000.0.
        Pass Settings().bankroll_usd for production use.
    daily_drawdown_limit:
        Fraction of bankroll as maximum daily exposure. Defaults to 0.05 (5%).

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

    quant_node = None
    if pool is not None:
        from sportsbet.graph.agents import make_quant_agent
        quant_node = make_quant_agent(pool)

    context_node = None
    if pool is not None and api_key is not None:
        from sportsbet.graph.agents import make_context_agent
        context_node = make_context_agent(pool, api_key, daily_credit_cap)

    arbitrage_node = None
    if pool is not None:
        from sportsbet.graph.agents import make_arbitrage_agent
        arbitrage_node = make_arbitrage_agent()

    kinematic_node = None
    if pool is not None:
        from sportsbet.graph.agents import make_kinematic_agent
        kinematic_node = make_kinematic_agent(pool)

    # Phase 13 Plan 02: prop pipeline nodes — gated on pool availability
    prop_quant_node = None
    nba_quant_node = None
    prop_arbitrage_node = None
    if pool is not None:
        from sportsbet.prop.agents import make_prop_quant_agent
        from sportsbet.prop.nba_agents import make_nba_quant_agent
        from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
        prop_quant_node = make_prop_quant_agent(pool)
        nba_quant_node = make_nba_quant_agent(pool)
        prop_arbitrage_node = make_prop_arbitrage_agent(sport=None)  # auto-detect NFL/NBA from state (Phase 14 — PROP-06)

    # Risk control nodes have no pool dependency — always constructed
    correlation_guard_node = make_correlation_guard_node()
    aggregator_node = make_aggregator_node(
        bankroll_usd=bankroll_usd,
        daily_drawdown_limit=daily_drawdown_limit,
    )

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    # Open a persistent aiosqlite connection for the graph's lifetime.
    conn = await aiosqlite.connect(db_path)
    saver = AsyncSqliteSaver(conn)
    return create_graph(
        checkpointer=saver,
        quant_node=quant_node,
        context_node=context_node,
        arbitrage_node=arbitrage_node,
        correlation_guard_node=correlation_guard_node,
        aggregator_node=aggregator_node,
        kinematic_node=kinematic_node,
        prop_quant_node=prop_quant_node,
        nba_quant_node=nba_quant_node,
        prop_arbitrage_node=prop_arbitrage_node,
    )
