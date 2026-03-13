"""Agent nodes for the LangGraph state machine.

Phase 3 Plan 01 adds make_quant_agent(pool) — an async closure factory that
replaces the sync stub quant_agent with a real QuantParams -> SQL -> QuantResult
pipeline. The sync stub is preserved for backward-compat with tests that don't
pass a pool to create_graph().

Phase replacement schedule:
- quant_agent (stub)  -> make_quant_agent(pool) closure (Phase 3, this plan)
- arbitrage_agent     -> Phase 5: real odds comparison against Odds API
- context_agent       -> Phase 4: real context stream processing (X/Twitter, Reddit, RSS)

Design: agents return dicts (partial state updates), not full GraphState.
LangGraph merges the returned dict into the current state using registered reducers.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import asyncpg
import structlog

from sportsbet.graph.models import EVSignal, QuantParams, QuantResult
from sportsbet.graph.state import GraphState

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level pool cache (lazy init for production entrypoint)
# ---------------------------------------------------------------------------

_pool: asyncpg.Pool | None = None


async def get_or_create_pool() -> asyncpg.Pool:
    """Return the module-level asyncpg pool, creating it lazily on first call.

    Used by production entrypoints that don't manage pool lifecycle externally.
    Tests should create their own pool and pass it to make_quant_agent() directly.
    """
    global _pool
    if _pool is None:
        from sportsbet.db.connection import create_async_pool
        _pool = await create_async_pool()
    return _pool


# ---------------------------------------------------------------------------
# Real quant agent — closure factory (Phase 3)
# ---------------------------------------------------------------------------

def make_quant_agent(
    pool: asyncpg.Pool,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    """Return an async quant agent node bound to the given asyncpg pool.

    The returned coroutine is compatible with LangGraph's async node interface:
    async def quant_agent(state: GraphState) -> dict

    Pipeline:
    1. Extract QuantParams from GraphState (raises ValidationError if invalid)
    2. Call run_quant_query(pool, params) to execute parameterized SQL
    3. Return partial state dict with quant_result set to QuantResult

    MIN_SAMPLE_SIZE gate is enforced inside run_quant_query — the agent always
    returns a valid QuantResult (possibly with data_source="insufficient_sample").
    """
    from sportsbet.quant.executor import run_quant_query

    async def quant_agent(state: GraphState) -> dict[str, Any]:  # type: ignore[type-arg]
        session_id = state["session_id"]
        log.info("quant_agent_invoked", session_id=session_id)

        try:
            params = QuantParams(
                game_id=state["game_id"],
                season=state["season"],
                week=state["week"],
                posteam=state["home_team"],  # default: query for home team offense
                stat_type="passing",         # default stat type; Context Agent will override
                filters={},
            )
            result = await run_quant_query(pool, params)
        except Exception as exc:
            log.error(
                "quant_agent_error",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            return {
                "quant_result": QuantResult(data_source="error"),
                "error": str(exc),
            }

        log.info(
            "quant_agent_complete",
            session_id=session_id,
            data_source=result.data_source,
            sample_size=result.sample_size,
        )
        return {"quant_result": result}

    return quant_agent


# ---------------------------------------------------------------------------
# Backward-compat sync stub (Phase 2 — preserved for test isolation)
# ---------------------------------------------------------------------------

def quant_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Quant Agent stub — returns a hardcoded QuantResult fixture instance.

    Preserved for backward-compat: create_graph() without a quant_node parameter
    uses this stub so all existing Phase 2 tests continue to pass without a DB.

    Phase 3 replacement: pass make_quant_agent(pool) as quant_node to create_graph().
    data_source="fixture" signals this is stub output (never from real SQL).
    """
    log.info("stub_agent_called", agent="quant_agent", session_id=state["session_id"])
    return {
        "quant_result": QuantResult(
            true_probability=Decimal("0.62"),
            sample_size=142,
            data_source="fixture",
        )
    }


# ---------------------------------------------------------------------------
# Stub agents — Phase 4/5 replacements pending
# ---------------------------------------------------------------------------

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
