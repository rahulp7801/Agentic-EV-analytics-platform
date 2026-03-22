"""GraphState TypedDict for the LangGraph agent state machine.

All fields are defined here. The `error` field uses an Annotated last-write-wins
reducer so LangGraph can handle concurrent writes without silent data loss.

Design notes (locked decisions from CONTEXT.md):
- Bankroll params (bankroll_usd, max_kelly_fraction) live in Settings, not GraphState.
- quant_result and ev_signal are typed as Any | None in Phase 2; Phase 3/5 narrow them.
- Only one agent runs per request so no true concurrent conflict on `error`, but
  Annotated is required for INFRA-01 compliance with LangGraph's reducer protocol.
- kinematic_result added in Phase 6: KinematicAnalysis | None, populated by
  make_kinematic_agent when request_type="kinematic_analysis".
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional, TypedDict

from sportsbet.graph.models import ContextSignals
from sportsbet.kinematic.models import KinematicAnalysis


def _last_write_wins(a: Any, b: Any) -> Any:  # noqa: ANN401
    """Reducer that returns the most recent (b) value, overwriting a.

    Used on the `error` field: only one agent writes per request cycle, so
    this is a last-write-wins semantic that preserves the latest error string
    or None reset.
    """
    return b


class GraphState(TypedDict):
    """Shared state passed between all LangGraph nodes.

    Fields
    ------
    session_id : str
        UUID string identifying the request session, set by the caller.
    request_type : str
        One of "quant_analysis" | "odds_check" | "context_update" | "arbitrage_analysis" | "kinematic_analysis".
        Master Router reads this to dispatch to the correct specialist agent.
    created_at : datetime
        UTC timestamp when the request was initiated.
    game_id : str
        Unique game identifier (e.g. "2025_01_KC_LAC").
    season : int
        NFL/NBA season year.
    week : int
        Week number within the season.
    home_team : str
        Home team abbreviation.
    away_team : str
        Away team abbreviation.
    injury_flags : dict[str, str]
        Maps player name to status string (e.g. {"P. Mahomes": "Questionable"}).
    weather_json : dict | None
        Weather context for outdoor games; None for indoor stadiums.
    error : Annotated[str | None, _last_write_wins]
        Error message set by any node. Master Router reads this at entry:
        if non-None, graph routes immediately to END without dispatching agents.
    quant_result : Any | None
        QuantResult instance set by quant_agent. Typed as Any in Phase 2;
        Phase 3 narrows to QuantResult after implementing real SQL queries.
    ev_signal : Any | None
        EVSignal instance set by arbitrage_agent. Typed as Any in Phase 2;
        Phase 5 narrows to EVSignal after implementing real odds comparison.
    context_signals : ContextSignals | None
        ContextSignals instance set by context_agent. None until Context Agent runs.
        Downstream agents must read odds and injury data from this field — never
        re-fetch from the API inside the Quant or Arbitrage agents.
    pending_signals : list[Any]
        EVSignal candidates produced by arbitrage_agent, before CorrelationGuard
        and Aggregator gate filtering. Overwritten each pipeline run (not appended).
    cleared_signals : list[Any]
        EVSignals that passed both CorrelationGuard.check() and Aggregator.record_signal().
        Populated by aggregator_node; empty list if no signals survive risk controls.
    receiver_gsis_id : str
        GSIS player ID passed to the Kinematic Agent for WR-CB matchup queries.
        Set by caller in initial state. Empty string ("") skips the kinematic query
        (make_kinematic_agent returns kinematic_result=None for zero NGS rows).
    """

    session_id: str
    request_type: str
    created_at: datetime
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    injury_flags: dict[str, str]
    weather_json: dict[str, Any] | None  # type: ignore[misc]
    error: Annotated[str | None, _last_write_wins]
    quant_result: Any | None  # type: ignore[misc]
    ev_signal: Any | None  # type: ignore[misc]
    context_signals: Optional[ContextSignals]  # type: ignore[misc]
    pending_signals: list[Any]  # type: ignore[misc]  # EVSignal candidates before CorrelationGuard check
    cleared_signals: list[Any]  # type: ignore[misc]  # Signals that passed CorrelationGuard AND Aggregator gate
    kinematic_result: Optional[KinematicAnalysis]  # type: ignore[misc]  # Set by make_kinematic_agent (Phase 6)
    receiver_gsis_id: str  # GSIS player ID for Kinematic Agent matchup queries (Phase 7 — INT-02)
