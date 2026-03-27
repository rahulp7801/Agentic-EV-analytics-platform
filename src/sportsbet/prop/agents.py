"""NFL player prop quant agent: make_prop_quant_agent closure factory.

Delivers the full production path for NFL player prop probability estimation:
Pydantic gate -> PropQueryBuilder SQL -> Wilson CI -> kinematic boost -> PropResult.

Kinematic integration (PROP-04): For receiving props (rec_yds, rec_tds, receptions),
the agent reads kinematic_result from GraphState and applies a separation-based
probability boost. When kinematic_result is None for a receiving prop, a WARNING is
logged — callers must use the PROP-04 two-invocation pattern (kinematic_agent first,
then prop_quant_agent in the same thread_id) to provide kinematic context.

Design mirrors make_quant_agent from sportsbet/graph/agents.py:
- Closure factory binds pool at construction time.
- Inner async function extracts PropParams fields from GraphState.
- ValidationError caught and returned as {"error": str(e)} — does not propagate to graph.
- Returns partial state dict: {"prop_result": PropResult}.

State key contract (GraphState fields read by this agent):
- receiver_gsis_id: str          — used as player_id (NFL receiver GSIS ID)
- season: int                    — query season
- game_id: str                   — propagated to PropParams for traceability
- prop_type: str | None          — defaults to "pass_yds" if absent
- prop_line: float | int | None  — converted to Decimal; defaults to "0"
- prop_filters: dict | None      — filter dict for week/team; defaults to {}
- sport: always "nfl" in this agent (NBA uses separate agent path)
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Coroutine, Optional

import asyncpg
import structlog
from pydantic import ValidationError

from sportsbet.graph.models import PropParams, PropResult
from sportsbet.graph.state import GraphState
from sportsbet.kinematic.models import KinematicAnalysis
from sportsbet.prop.executor import run_prop_query

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Kinematic adjustment constants (Plan 02)
# ---------------------------------------------------------------------------

KINEMATIC_BOOST: Decimal = Decimal("0.05")
RECEIVING_PROPS: frozenset[str] = frozenset({"rec_yds", "rec_tds", "receptions"})


# ---------------------------------------------------------------------------
# Kinematic adjustment — full implementation (Plan 02)
# ---------------------------------------------------------------------------

def _apply_kinematic_adjustment(
    result: PropResult,
    kinematic: Optional[KinematicAnalysis],
    prop_type: str,
) -> PropResult:
    """Apply kinematic geometric mismatch adjustment to prop probability.

    Applies an additive KINEMATIC_BOOST (0.05) to true_probability when:
    - kinematic is not None
    - prop_type is in RECEIVING_PROPS (rec_yds, rec_tds, receptions)
    - result.true_probability is not None
    - kinematic.geometric_mismatch_flag is True

    Output is clamped to [0.01, 0.99] — never exceeds 1.0 or drops below 0.0.
    press_man_rate is NEVER read (always None per Phase 6 decision).

    Parameters
    ----------
    result:
        Base PropResult from run_prop_query (Wilson CI already computed).
    kinematic:
        KinematicAnalysis from make_kinematic_agent, or None when kinematic
        data is unavailable (NGS not available for season, or kinematic node
        not wired in graph for this request type).
    prop_type:
        PropParams.prop_type — determines which props are eligible for
        kinematic adjustment (receiving props only).

    Returns
    -------
    PropResult
        Adjusted PropResult with boosted true_probability and updated
        data_source, or original result when conditions are not met.
    """
    if kinematic is None:
        return result
    if prop_type not in RECEIVING_PROPS:
        return result
    if result.true_probability is None:
        return result
    if not kinematic.geometric_mismatch_flag:
        return result

    adjusted = result.true_probability + KINEMATIC_BOOST
    adjusted = max(Decimal("0.01"), min(Decimal("0.99"), adjusted))
    return result.model_copy(update={"true_probability": adjusted, "data_source": "postgresql+kinematic"})


# ---------------------------------------------------------------------------
# Closure factory
# ---------------------------------------------------------------------------

def make_prop_quant_agent(
    pool: asyncpg.Pool,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    """Return an async prop quant agent node bound to the given asyncpg pool.

    The returned coroutine is compatible with LangGraph's async node interface:
    async def prop_quant_agent(state: GraphState) -> dict

    Pipeline:
    1. Extract PropParams fields from GraphState
    2. Validate with Pydantic PropParams (raises ValidationError if invalid)
    3. Call run_prop_query(pool, params) -> base PropResult
    4. Call _apply_kinematic_adjustment(result, state["kinematic_result"], prop_type) — Plan 02 real boost
    5. Return partial state dict: {"prop_result": result}

    On ValidationError: return {"error": str(e)} — does not propagate to graph.

    Parameters
    ----------
    pool:
        asyncpg connection pool. Injected at construction time so the agent
        closure holds a stable reference throughout the process lifetime.

    Invocation ordering (CTXT-04/PROP-04):
        For situational_params (injury-adjusted queries), callers must invoke
        "context_update" before "prop_analysis" in the same thread_id. The context_agent
        populates situational_params in GraphState; prop_quant_agent reads it via
        state.get("situational_params") or {}.

        When no prior context_update has been called, situational_params is None.
        The agent falls back to {} (empty dict), which means teammate_out=None in
        PropParams — the query runs without injury-adjusted WHERE clauses. This is
        the correct production fallback for callers that run prop queries without
        injury context.
    """

    async def prop_quant_agent(state: GraphState) -> dict[str, Any]:  # type: ignore[type-arg]
        session_id = state.get("session_id", "unknown")  # type: ignore[union-attr]
        log.info("prop_quant_agent_invoked", session_id=session_id)

        try:
            # Extract PropParams fields from GraphState
            # player_id comes from receiver_gsis_id (set by kinematic routing or context agent)
            player_id: str = state.get("receiver_gsis_id", "")  # type: ignore[union-attr]
            season: int = state["season"]
            game_id: str = state["game_id"]
            prop_type: str = state.get("prop_type", "pass_yds")  # type: ignore[union-attr]
            prop_line_raw = state.get("prop_line", "0")  # type: ignore[union-attr]
            prop_filters: dict[str, object] = state.get("prop_filters", {})  # type: ignore[union-attr]
            situational: dict = state.get("situational_params") or {}  # type: ignore[union-attr]
            teammate_out: list[str] | None = situational.get("teammate_out_signals") or None

            # Convert line to Decimal — prop_line may arrive as float, int, str, or Decimal
            line = Decimal(str(prop_line_raw if prop_line_raw is not None else "0"))

            params = PropParams(
                game_id=game_id,
                player_id=player_id,
                season=season,
                sport="nfl",
                prop_type=prop_type,  # type: ignore[arg-type]
                line=line,
                filters=prop_filters if prop_filters else {},
                teammate_out=teammate_out,
            )
        except ValidationError as exc:
            log.error(
                "prop_quant_agent_validation_error",
                session_id=session_id,
                error=str(exc),
            )
            return {"error": str(exc)}

        try:
            # Run parameterized SQL query against player_stats
            result = await run_prop_query(pool, params)
        except Exception as exc:
            log.error(
                "prop_quant_agent_query_error",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            return {
                "prop_result": PropResult(data_source="error"),
                "error": str(exc),
            }

        # Apply kinematic adjustment — reads kinematic_result from GraphState (Plan 02)
        kinematic_result: Optional[KinematicAnalysis] = state.get("kinematic_result")  # type: ignore[union-attr]
        if kinematic_result is None and params.prop_type in RECEIVING_PROPS:
            log.warning(
                "prop_quant_agent_kinematic_missing",
                session_id=session_id,
                prop_type=params.prop_type,
            )
        result = _apply_kinematic_adjustment(result, kinematic_result, params.prop_type)

        log.info(
            "prop_quant_agent_complete",
            session_id=session_id,
            data_source=result.data_source,
            sample_size=result.sample_size,
        )
        return {"prop_result": result}

    return prop_quant_agent
