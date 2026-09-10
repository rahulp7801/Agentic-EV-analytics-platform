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

from datetime import date, datetime
from typing import Annotated, Any, Optional, TypedDict

from sportsbet.graph.models import ContextSignals, NBAContextSignals, PropResult
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
    prop_result : PropResult | None
        PropResult instance set by make_prop_quant_agent. None until Prop Quant Agent
        runs. Incorporates kinematic boost when kinematic_result is available and
        geometric_mismatch_flag=True for receiving props.
    nba_context_signals : NBAContextSignals | None
        NBA-specific contextual signals set by caller before NBA prop queries.
        Carries pace_factor, opponent_def_rating, rest_days, and is_home through
        GraphState for consumption by make_nba_quant_agent (Phase 12).
        None when request is NFL (non-NBA) or NBA context not provided.
    nba_prop_result : PropResult | None
        PropResult instance set by make_nba_quant_agent. None until NBA Quant Agent
        runs. Incorporates four-stage contextual adjustment when nba_context_signals
        is present: pace -> def_rating -> rest_penalty -> home_boost (Phase 12).
    prop_type : str
        Prop market type identifier passed to PropArbitrageAgent (Phase 13).
        Examples: "pass_yds", "rec_yds", "rush_yds", "pass_tds", "points", "pra".
        Always set by caller for prop_analysis routes; non-prop routes may omit
        (access via state.get("prop_type") to avoid KeyError).
    prop_line : Any
        Numeric or string line value for the prop bet (Phase 13).
        Examples: "250.5" (passing yards), 22.5 (points). Typed as Any to match
        the flex-typed contract of PropParams.line and NBA prop queries.
        Access via state.get("prop_line") — not required for non-prop routes.
    prop_filters : dict[str, Any] | None
        Optional prop filter context passed to PropQueryBuilder and NBAQueryBuilder.
        None for non-prop routes. Access via state.get("prop_filters") or {} in agents.
        Declared here per INFRA-01 — agents used state.get() workaround before Phase 14.
    sport : str | None
        Sport context for the request: "nfl" | "nba" | None.
        None and "nfl" are treated identically — context agent defaults to NFL odds.
        Set to "nba" to route context agent to fetch_nba_odds() (Phase 15 — CTXT-04).
        Access via state.get("sport") or "nfl" in agents — never require presence.
    situational_params : dict[str, Any] | None
        Situational filter context injected by ContextAgent after news/injury parsing
        (Phase 18 — SC-3). Non-None when injury_flags contains Out/Inactive players.
        Contains "teammate_out_signals" list for use by PropQueryBuilder in Plan 03.
        None for routes with no relevant injury context. Access via state.get().
    player_prop_snapshots : list[Any] | None
        List of PlayerPropSnapshotCreate objects produced during Step 1c of
        context_agent (Phase 23 — PROP-06). Populated when Odds API player prop
        markets are successfully fetched. None when fetch fails or list is empty.
        PropArbitrageAgent matches against this list to obtain a prop-specific
        implied_probability (commensurable with prop_result.true_probability).
        Access via state.get("player_prop_snapshots").
    stat_type : str | None
        Quant stat category override: "passing" | "rushing" | "receiving" | None.
        None means quant_agent defaults to "passing". Written by context_agent when
        request context indicates non-passing analysis. Access via state.get().
        (quick-1 — QUANT-03)
    """

    session_id: str
    request_type: str
    created_at: datetime
    as_of_date: date | None  # Exclusive history cutoff for NBA predictions.
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
    prop_result: Optional[PropResult]  # type: ignore[misc]  # Set by make_prop_quant_agent (Phase 11)
    nba_context_signals: Optional[NBAContextSignals]  # type: ignore[misc]  # Set by caller for NBA prop queries (Phase 12)
    nba_prop_result: Optional[PropResult]  # type: ignore[misc]  # Set by make_nba_quant_agent (Phase 12)
    prop_type: str  # Prop market type identifier for PropArbitrageAgent (Phase 13 — PROP-06)
    gate_reason: str | None
    prop_side: str  # over/under; PropResult stores Over probability.
    prop_line: Any  # type: ignore[misc]  # Numeric/string prop line value (Phase 13 — PROP-06)
    prop_filters: dict[str, Any] | None  # type: ignore[misc]  # Optional prop filter context; None for non-prop routes (Phase 14 — INFRA-01)
    sport: str | None  # type: ignore[misc]  # "nfl" | "nba" — None defaults to "nfl" in context agent (Phase 15 — CTXT-04)
    situational_params: dict[str, Any] | None  # type: ignore[misc]  # Injected by ContextAgent after news parsing (Phase 18 — SC-3)
    player_prop_snapshots: list[Any] | None  # type: ignore[misc]
    # PlayerPropSnapshotCreate list from context_agent Step 1c (Phase 23 — PROP-06)
    stat_type: str | None  # type: ignore[misc]
    # Quant stat category override: "passing" | "rushing" | "receiving" | None.
    # None means quant_agent defaults to "passing". Set by context_agent when
    # request context indicates non-passing play analysis.
    # Access via state.get("stat_type", "passing") — never require presence.
    # (quick-1 — QUANT-03)
    player_name: str  # Display name of the player being analysed (e.g. "Jayson Tatum").
    # Used by arbitrage_agent to look up the matching player prop snapshot.
    # Access via state.get("player_name", "") — not required for non-prop routes.
