"""NBA prop quant agent: make_nba_quant_agent closure factory.

Phase 12 Plan 02: Wraps the NormalDist probability engine from Plan 01
(run_nba_prop_query) in a LangGraph-compatible agent node. Reads NBAContextSignals
from GraphState and applies the four-stage contextual adjustment pipeline to
produce a matchup-specific probability.

Four-stage adjustment pipeline (applied by _apply_nba_context_adjustments):
    1. Pace:        prob *= clamp(pace_factor / LEAGUE_AVG_PACE, 0.5, 1.5)
                    — only for PACE_ADJUSTED_PROPS (points, rebounds, assists, pra)
    2. Def rating:  prob *= clamp(LEAGUE_AVG_DEF_RATING / opponent_def_rating, 0.7, 1.3)
                    — higher opponent_def_rating = worse defense = more scoring
    3. Rest:        prob -= REST_PENALTY (0.03) when rest_days == 0 (back-to-back)
    4. Home:        prob += HOME_BOOST (0.015) when is_home == True
    5. Clamp:       prob = max(0.01, min(0.99, prob))

PACE_ADJUSTED_PROPS restriction:
    Pace adjustment is only meaningful for volume counting stats (points, rebounds,
    assists, pra). Efficiency props (threes, steals, blocks) are not pace-sensitive
    because they depend on skill rate, not possession count. See nba_query_builder.py
    for the frozenset definition.

Contextual independence:
    All values in NBAContextSignals come from caller-supplied live data or fixture
    inputs — never inferred by LLM. The agent reads state["nba_context_signals"]
    directly; if None, base probability from Plan 01 is returned unchanged.

Request routing:
    request_type="nba_prop_analysis" routes here via route_from_master (Phase 13).
    State keys read: receiver_gsis_id (as player_id), season, game_id, prop_type,
    prop_line, prop_filters, nba_context_signals.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Coroutine, Optional

import asyncpg
import structlog
from pydantic import ValidationError

from sportsbet.graph.models import NBAContextSignals, PropParams, PropResult
from sportsbet.graph.state import GraphState
from sportsbet.prop.nba_executor import (
    HOME_BOOST,
    LEAGUE_AVG_DEF_RATING,
    LEAGUE_AVG_PACE,
    REST_PENALTY,
    run_nba_prop_query,
)
from sportsbet.prop.nba_query_builder import PACE_ADJUSTED_PROPS

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Internal helper: four-stage contextual adjustment pipeline
# ---------------------------------------------------------------------------


def _apply_nba_context_adjustments(
    result: PropResult,
    context: Optional[NBAContextSignals],
    prop_type: str,
) -> PropResult:
    """Apply pace, defensive rating, rest, and home/away adjustments to base probability.

    Returns result unchanged when:
    - context is None (no NBA context signals in GraphState)
    - result.true_probability is None (insufficient sample from Plan 01)

    Adjustment pipeline (sequential):
    1. Pace: prob *= clamp(pace_factor / LEAGUE_AVG_PACE, 0.5, 1.5)
       — only for PACE_ADJUSTED_PROPS
    2. Def rating: prob *= clamp(LEAGUE_AVG_DEF_RATING / opponent_def_rating, 0.7, 1.3)
    3. Rest: prob -= REST_PENALTY when rest_days == 0
    4. Home: prob += HOME_BOOST when is_home == True
    5. Clamp: max(0.01, min(0.99, prob))

    All constants imported from nba_executor.py: LEAGUE_AVG_PACE,
    LEAGUE_AVG_DEF_RATING, REST_PENALTY, HOME_BOOST.

    Parameters
    ----------
    result:
        Base PropResult from run_nba_prop_query (NormalDist CDF already computed).
    context:
        NBAContextSignals from GraphState, or None when not provided.
    prop_type:
        PropParams.prop_type — gates pace adjustment to PACE_ADJUSTED_PROPS only.

    Returns
    -------
    PropResult
        Adjusted PropResult with updated true_probability and data_source,
        or the original result object when conditions are not met.
    """
    if context is None or result.true_probability is None:
        return result

    prob = result.true_probability  # Decimal

    # Stage 1: Pace adjustment (volume props only)
    if prop_type in PACE_ADJUSTED_PROPS:
        pace_ratio = context.pace_factor / LEAGUE_AVG_PACE
        pace_ratio = max(Decimal("0.5"), min(Decimal("1.5"), pace_ratio))
        prob = prob * pace_ratio

    # Stage 2: Opponent defensive rating adjustment
    # Higher opponent_def_rating = worse defense = more scoring opportunity
    def_ratio = LEAGUE_AVG_DEF_RATING / context.opponent_def_rating
    def_ratio = max(Decimal("0.7"), min(Decimal("1.3"), def_ratio))
    prob = prob * def_ratio

    # Stage 3: Back-to-back rest penalty
    if context.rest_days == 0:
        prob = prob - REST_PENALTY

    # Stage 4: Home court boost
    if context.is_home:
        prob = prob + HOME_BOOST

    # Stage 5: Clamp to valid probability domain
    prob = max(Decimal("0.01"), min(Decimal("0.99"), prob))

    return result.model_copy(update={"true_probability": prob, "data_source": "postgresql+nba_context"})


# ---------------------------------------------------------------------------
# Closure factory
# ---------------------------------------------------------------------------


def make_nba_quant_agent(
    pool: asyncpg.Pool,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    """Return an async NBA prop quant agent node bound to the given asyncpg pool.

    The returned coroutine is compatible with LangGraph's async node interface:
    async def nba_quant_agent(state: GraphState) -> dict

    Pipeline:
    1. Extract PropParams fields from GraphState (sport fixed to "nba")
    2. Validate with Pydantic PropParams (raises ValidationError if invalid)
    3. Call run_nba_prop_query(pool, params) -> base PropResult (NormalDist CDF)
    4. Read nba_context_signals from GraphState
    5. Call _apply_nba_context_adjustments(result, context, prop_type)
    6. Return partial state dict: {"nba_prop_result": result}

    On ValidationError: return {"error": str(exc)} — does not propagate to graph.

    Parameters
    ----------
    pool:
        asyncpg connection pool. Injected at construction time so the agent
        closure holds a stable reference throughout the process lifetime.

    Invocation ordering (CTXT-04/PROP-04):
        For NBA context adjustments (pace, def_rating, rest, home/away), the graph
        automatically inserts nba_context_producer before nba_quant_agent (see graph.py
        nba_context_producer -> nba_quant_agent edge). Callers using request_type=
        "nba_prop_analysis" do not need to manually invoke a separate context step —
        nba_context_producer runs automatically in the same ainvoke call.

        When nba_context_signals is None (stub path or producer returns None), all four
        context adjustments are skipped and the base NormalDist CDF probability from
        run_nba_prop_query is returned unchanged. This is the correct fallback for
        callers where live NBA context data is unavailable.
    """

    async def nba_quant_agent(state: GraphState) -> dict[str, Any]:  # type: ignore[type-arg]
        session_id = state.get("session_id", "unknown")  # type: ignore[union-attr]
        log.info("nba_quant_agent_invoked", session_id=session_id)

        try:
            # receiver_gsis_id is reused as player_id for NBA (cross-sport field)
            player_id: str = state.get("receiver_gsis_id", "")  # type: ignore[union-attr]
            season: int = state["season"]
            game_id: str = state["game_id"]
            prop_type: str = state.get("prop_type", "points")  # type: ignore[union-attr]
            prop_line_raw = state.get("prop_line", "0")  # type: ignore[union-attr]
            prop_filters: dict[str, object] = state.get("prop_filters", {})  # type: ignore[union-attr]
            situational: dict = state.get("situational_params") or {}  # type: ignore[union-attr]
            teammate_out: list[str] | None = situational.get("teammate_out_signals") or None
            teammate_out_contexts: list[dict[str, str]] | None = situational.get("teammate_out_contexts") or None

            # Convert line to Decimal — prop_line may arrive as float, int, str, or Decimal
            line = Decimal(str(prop_line_raw if prop_line_raw is not None else "0"))

            params = PropParams(
                game_id=game_id,
                player_id=player_id,
                season=season,
                sport="nba",
                prop_type=prop_type,  # type: ignore[arg-type]
                line=line,
                filters=prop_filters if prop_filters else {},
                teammate_out=teammate_out,
                teammate_out_contexts=teammate_out_contexts,
            )
        except ValidationError as exc:
            log.error(
                "nba_quant_agent_validation_error",
                session_id=session_id,
                error=str(exc),
            )
            return {"error": str(exc)}

        try:
            result = await run_nba_prop_query(pool, params)
        except Exception as exc:
            log.error(
                "nba_quant_agent_query_error",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            return {
                "nba_prop_result": PropResult(data_source="error"),
                "error": str(exc),
            }

        # Apply contextual adjustments from NBAContextSignals in GraphState
        context_signals: Optional[NBAContextSignals] = state.get("nba_context_signals")  # type: ignore[union-attr]
        result = _apply_nba_context_adjustments(result, context_signals, params.prop_type)

        log.info(
            "nba_quant_agent_complete",
            session_id=session_id,
            data_source=result.data_source,
            sample_size=result.sample_size,
        )
        return {"nba_prop_result": result}

    return nba_quant_agent
