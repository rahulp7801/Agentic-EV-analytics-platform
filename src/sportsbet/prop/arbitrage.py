"""PropArbitrageAgent closure factory for player prop markets.

Mirrors the structure of make_arbitrage_agent (Phase 5) but reads prop-specific
state keys (prop_result / nba_prop_result) and generates a prop-aware trade plan
via _build_prop_trade_plan.

Exports
-------
make_prop_arbitrage_agent
    Closure factory accepting sport="nfl"|"nba". Returns an async LangGraph node
    function that computes EV%, Kelly sizing, and a 3-bullet Trade Plan for the
    player prop market indicated by context_signals.odds_snapshot.market_type.

Design rules (locked from CLAUDE.md and Phase decisions):
- All Decimal arithmetic uses Decimal — never float, never int cast
- max_kelly_fraction from Settings (Decimal(str(cfg.max_kelly_fraction))) — locked Phase 2 pattern
- EVSignal reused — no new Pydantic model (RESEARCH.md anti-pattern note)
- structlog used for all structured logging
- All guards return {"ev_signal": None} (not raise) — LangGraph continuity
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

import structlog

from sportsbet.arbitrage.ev import compute_ev_percentage, compute_expected_return, quote_terms
from sportsbet.arbitrage.kelly import fractional_kelly
from sportsbet.config import settings as _settings
from sportsbet.graph.models import EVSignal, NBAContextSignals, PropResult
from sportsbet.graph.state import GraphState

log = structlog.get_logger()

_NO_SIGNAL: dict[str, Any] = {"ev_signal": None, "pending_signals": []}

# EV ceiling: any signal above this is almost certainly a model artifact
# (NormalDist overconfidence vs. easy/goblin lines, or stale season-avg).
# Real exploitable edges in liquid prop markets are typically 1–8%.
# 15% is a hard upper bound — if the model claims more, suppress the signal.
_EV_CAP: Decimal = Decimal("0.15")

# Alias map: PropParams Literal shorthand -> Odds API market key format.
# Used by prop_arbitrage_agent to match state["prop_type"] against
# PlayerPropSnapshotCreate.prop_type (which stores raw Odds API market keys).
# (Phase 23 — PROP-06)
_PROP_TYPE_ALIAS_MAP: dict[str, str] = {
    "pass_yds": "player_pass_yds",        # was player_pass_yards — NFL_PROP_MARKETS key
    "rush_yds": "player_rush_yds",        # was player_rush_yards — NFL_PROP_MARKETS key
    "rec_yds": "player_reception_yds",    # was player_receiving_yards — NFL_PROP_MARKETS key (PROP-06)
    "pass_tds": "player_pass_tds",
    "rush_tds": "player_rush_tds",        # added — present in NFL_PROP_MARKETS, was missing
    "rec_tds": "player_reception_tds",    # added — present in NFL_PROP_MARKETS, was missing
    "receptions": "player_receptions",
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "threes": "player_threes",    # added — scan_game_ev strips "player_" prefix
    "steals": "player_steals",    # added — same prefix-stripping issue
    "blocks": "player_blocks",    # added — same prefix-stripping issue
    "pra": "player_pra",
}


_LEAGUE_AVG_DEF_RATING: float = 115.0
_REST_PENALTY_PP: float = 3.0     # percentage points removed for back-to-back
_HOME_BOOST_PP: float = 1.5       # percentage points added for home court


def _direction_interval(
    prop_result: PropResult,
    direction: str,
) -> tuple[Decimal, Decimal] | None:
    """Return a validated unconditional interval for the requested side."""
    interval = prop_result.confidence_interval
    push_probability = prop_result.push_probability
    non_push_probability = Decimal("1") - push_probability
    if interval is None or not 0 <= push_probability < 1:
        return None
    lower, upper = interval
    if not all(value.is_finite() for value in (lower, upper)):
        return None
    if not 0 <= lower <= upper <= non_push_probability:
        return None
    if direction == "over":
        return lower, upper
    return non_push_probability - upper, non_push_probability - lower


def _build_prop_trade_plan(
    ev_pct: Decimal,
    kelly_frac: Decimal,
    injury_flags: dict[str, str],
    market_type: str,
    prop_result: PropResult,
    nba_context: Optional[NBAContextSignals] = None,
    teammate_out: Optional[list[str]] = None,
) -> list[str]:
    """Build a 3-bullet prop-specific trade plan thesis.

    For NBA (nba_context provided):
        Bullet 1: EV edge + historical base (n, mean).
        Bullet 2: Context adjustments applied — opponent def rating, rest, home/away.
        Bullet 3: Kelly sizing + injury flags.

    For NFL (nba_context=None):
        Bullet 1: probability edge on the specific prop market.
        Bullet 2: Kelly sizing with sample_size and mean_stat from PropResult.
        Bullet 3: injury flags or clean bill of health.

    Parameters
    ----------
    ev_pct : Decimal
        Positive EV percentage from compute_ev_percentage.
    kelly_frac : Decimal
        Fractional Kelly stake as bankroll fraction from fractional_kelly.
    injury_flags : dict[str, str]
        Player-to-status mapping from ContextSignals.injury_flags.
    market_type : str
        Market identifier from AgentOddsSnapshot (e.g. "over_pass_yds").
    prop_result : PropResult
        Carries sample_size and mean_stat for bullet context.
    nba_context : NBAContextSignals, optional
        When provided, bullet 2 becomes a context-adjustment summary instead of
        Kelly sizing, and NBA-specific factors are surfaced explicitly.

    Returns
    -------
    list[str]
        Exactly 3 non-empty strings.
    """
    sample = prop_result.sample_size if prop_result.sample_size is not None else "N/A"
    mean = (
        f"{float(prop_result.mean_stat):.1f}"
        if prop_result.mean_stat is not None
        else "N/A"
    )
    kelly_str = f"Kelly: {float(kelly_frac):.1%} bankroll stake (fractional, not flat)"

    if nba_context is not None and _settings.experimental_probability_adjustments:
        # Bullet 1: historical base + EV edge
        bullet_1 = (
            f"+{float(ev_pct):.1%} probability edge on {market_type} | "
            f"n={sample} games, mean={mean} historical"
        )

        # Bullet 2: context adjustment chain
        def_rating = float(nba_context.opponent_def_rating)
        def_delta = def_rating - _LEAGUE_AVG_DEF_RATING
        if def_delta > 0.5:
            def_tag = f"opp def {def_rating:.1f} > avg {_LEAGUE_AVG_DEF_RATING:.0f} (weak D → scoring boost)"
        elif def_delta < -0.5:
            def_tag = f"opp def {def_rating:.1f} < avg {_LEAGUE_AVG_DEF_RATING:.0f} (strong D → prob suppressed)"
        else:
            def_tag = f"opp def {def_rating:.1f} ≈ league avg (neutral)"

        rest_days = nba_context.rest_days
        if rest_days == 0:
            rest_tag = f"B2B (−{_REST_PENALTY_PP:.0f}pp fatigue penalty applied)"
        elif rest_days == 1:
            rest_tag = "1d rest (standard)"
        else:
            rest_tag = f"{rest_days}d rest (well-rested)"

        home_tag = (
            f"HOME (+{_HOME_BOOST_PP:.1f}pp boost applied)"
            if nba_context.is_home
            else "AWAY (no home boost)"
        )

        teammate_tag = ""
        if teammate_out:
            absent = ", ".join(teammate_out[:2])
            teammate_tag = f" · sample conditioned on {absent} inactive"
        bullet_2 = f"Context: {def_tag} · {rest_tag} · {home_tag}{teammate_tag}"

        # Bullet 3: Kelly sizing + injury
        if injury_flags:
            flagged = ", ".join(f"{p} ({s})" for p, s in injury_flags.items())
            bullet_3 = f"{kelly_str} · Injury flags: {flagged}"
        else:
            bullet_3 = f"{kelly_str} · No verified injury flags supplied"

    else:
        # NFL path (no nba_context)
        bullet_1 = f"+{float(ev_pct):.1%} probability edge on {market_type} prop market"
        bullet_2 = (
            f"Kelly sizing: {float(kelly_frac):.1%} fractional stake "
            f"(n={sample}, historical mean={mean}, bankroll-relative)"
        )
        if injury_flags:
            flagged = ", ".join(f"{p} ({s})" for p, s in injury_flags.items())
            bullet_3 = f"Material injury flags: {flagged}"
        else:
            bullet_3 = "No verified injury flags supplied for this game"

    return [bullet_1, bullet_2, bullet_3]


def make_prop_arbitrage_agent(
    settings_override: Any = None,
    sport: str | None = "nfl",
) -> Any:
    """Closure factory for the PropArbitrageAgent LangGraph node.

    Parameters
    ----------
    settings_override : object, optional
        If provided, used as cfg instead of global settings.
        Useful for tests that need custom max_kelly_fraction values.
    sport : str | None
        "nfl" reads state["prop_result"]; "nba" reads state["nba_prop_result"].
        None auto-detects: prefers nba_prop_result if present, else falls back to
        prop_result. Resolved at runtime inside the closure (Phase 14 — PROP-06).
        Default is "nfl".

    Returns
    -------
    Callable[[GraphState], Awaitable[dict]]
        Async LangGraph node function. Returns dict with:
        - {"ev_signal": None} when guards fire (no data, -EV, missing snapshot)
        - {"ev_signal": EVSignal, "pending_signals": [EVSignal]} for +EV props
    """
    cfg = settings_override if settings_override is not None else _settings

    async def prop_arbitrage_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
        """Compute EV% and Kelly fraction for a player prop market.

        Reads PropResult from the resolved state key and ContextSignals.odds_snapshot
        to produce an EVSignal with 3-bullet trade plan and fractional Kelly size.
        Returns {"ev_signal": None} for any guard condition (missing data, -EV).

        When sport is None, auto-detects: prefers nba_prop_result if present,
        else falls back to prop_result (Phase 14 — PROP-06).
        """
        # Resolve sport and state key at runtime (not factory construction time)
        # so sport=None can inspect live state for auto-detection.
        if sport is None:
            _nba = state.get("nba_prop_result")  # type: ignore[attr-defined]
            prop_result: PropResult | None = _nba or state.get("prop_result")  # type: ignore[assignment]
            resolved_sport = "nba" if _nba is not None else "nfl"
        else:
            _state_key = "nba_prop_result" if sport == "nba" else "prop_result"
            prop_result = state.get(_state_key)  # type: ignore[assignment]
            resolved_sport = sport

        log.info("prop_arbitrage_agent.enter", sport=resolved_sport)

        if state.get("error"):
            return {**_NO_SIGNAL, "cleared_signals": [], "gate_reason": "model_error"}

        # Guard 1: prop_result must exist with a real probability
        if prop_result is None or prop_result.true_probability is None:
            log.info(
                "prop_arbitrage_agent.no_prop_result",
                sport=resolved_sport,
                reason="prop_result is None or true_probability is None",
            )
            return _NO_SIGNAL

        if (prop_result.sample_size or 0) < 20:
            return {**_NO_SIGNAL, "gate_reason": "insufficient_sample"}
        direction = state.get("prop_side", "over").lower()
        if direction not in ("over", "under"):
            return _NO_SIGNAL

        # Guard 2a: try player_prop_snapshots match path (Phase 23 — PROP-06 fix)
        # Reads player_prop_snapshots from state, normalizes prop_type shorthand to
        # Odds API market key, and matches on (prop_type, line) for commensurable EV.
        snapshots: list | None = state.get("player_prop_snapshots")  # type: ignore[attr-defined]
        target_prop_type: str = state.get("prop_type", "")  # type: ignore[attr-defined]
        # Normalize PropParams shorthand (e.g. "pass_yds") to Odds API market key (e.g. "player_pass_yards")
        normalized_prop_type = _PROP_TYPE_ALIAS_MAP.get(target_prop_type, target_prop_type)
        raw_line = state.get("prop_line")  # type: ignore[attr-defined]
        target_line: Decimal | None = None
        if raw_line is not None:
            try:
                target_line = Decimal(str(raw_line))
            except Exception:
                pass

        target_player: str = state.get("player_name", "")  # type: ignore[attr-defined]
        matched_snapshot = None
        if snapshots:
            for snap in snapshots:
                type_match = snap.prop_type == normalized_prop_type
                line_match = target_line is not None and snap.line == target_line
                player_match = bool(target_player) and target_player.strip().casefold() == snap.player_name.strip().casefold()
                side_match = (snap.side or "").casefold() == direction
                if type_match and line_match and player_match and side_match:
                    matched_snapshot = snap
                    break

        # Determine implied_prob, market_type, injury_flags from matched snapshot or fallback
        context_signals = state.get("context_signals")  # type: ignore[attr-defined]
        if matched_snapshot is not None:
            if matched_snapshot.sportsbook.lower() == "prizepicks":
                return {**_NO_SIGNAL, "gate_reason": "synthetic_price"}
            implied_prob: Decimal = matched_snapshot.implied_probability
            american_odds = matched_snapshot.price
            market_type: str = matched_snapshot.prop_type
            injury_flags: dict[str, str] = (
                context_signals.injury_flags
                if context_signals is not None
                else {}
            )
        else:
            # A game-moneyline quote cannot price a player prop. Fail closed.
            return {**_NO_SIGNAL, "gate_reason": "missing_matching_prop_quote"}

        push_prob = prop_result.push_probability
        true_prob: Decimal = prop_result.true_probability if direction == "over" else Decimal("1") - prop_result.true_probability - push_prob
        if not 0 <= push_prob < 1 or not 0 <= true_prob <= 1 - push_prob:
            return _NO_SIGNAL

        try:
            implied_prob, net_payout = quote_terms(american_odds, implied_prob)
        except ValueError:
            return _NO_SIGNAL

        # EV computation — floored at 0
        implied_prob *= 1 - push_prob
        ev_pct = compute_ev_percentage(true_prob, implied_prob)
        if ev_pct == Decimal("0"):
            log.info(
                "prop_arbitrage_agent.no_ev",
                sport=resolved_sport,
                market_type=market_type,
                true_prob=str(true_prob),
                implied_prob=str(implied_prob),
            )
            return _NO_SIGNAL

        confidence_interval = _direction_interval(prop_result, direction)
        if confidence_interval is None:
            return {**_NO_SIGNAL, "gate_reason": "uncertainty_unavailable"}
        if confidence_interval[0] <= implied_prob:
            return {**_NO_SIGNAL, "gate_reason": "edge_not_confident"}

        # EV ceiling guard: suppress signals the model can't reliably produce.
        # Real prop edges are 1–8%; anything above _EV_CAP (15%) is almost
        # certainly NormalDist overconfidence vs. an easy/goblin line, not a
        # genuine market inefficiency. Log the suppression so it is auditable.
        if ev_pct > _EV_CAP:
            log.warning(
                "prop_arbitrage_agent.ev_cap_exceeded",
                sport=resolved_sport,
                market_type=market_type,
                ev_pct=str(ev_pct),
                true_prob=str(true_prob),
                implied_prob=str(implied_prob),
                reason="ev_pct > _EV_CAP — likely model overconfidence or easy/goblin line",
            )
            return {**_NO_SIGNAL, "gate_reason": "edge_review_limit"}

        # Kelly sizing — Decimal(str(...)) pattern locked in Phase 2
        kelly_frac = fractional_kelly(
            p=confidence_interval[0] / (1 - push_prob),
            b=net_payout,
            fraction=Decimal(str(cfg.max_kelly_fraction)),
        )

        # Guard: kelly_fraction must be positive to produce a valid EVSignal
        if kelly_frac <= Decimal("0"):
            log.info(
                "prop_arbitrage_agent.zero_kelly",
                sport=resolved_sport,
                market_type=market_type,
                kelly_frac=str(kelly_frac),
            )
            return _NO_SIGNAL

        # Read NBA context signals for context-aware bullet 2
        nba_context: Optional[NBAContextSignals] = state.get("nba_context_signals")  # type: ignore[attr-defined]

        # Pull teammate_out list from situational_params so bullet_2 surfaces it
        _situational: dict = state.get("situational_params") or {}  # type: ignore[attr-defined]
        _teammate_out_for_plan: Optional[list[str]] = _situational.get("teammate_out_signals") or None

        # 3-bullet prop-aware trade plan — NBA path surfaces context adjustments
        trade_plan = _build_prop_trade_plan(
            ev_pct, kelly_frac, injury_flags, market_type, prop_result, nba_context,
            teammate_out=_teammate_out_for_plan,
        )

        signal = EVSignal(
            ev_percentage=ev_pct,
            expected_return=compute_expected_return(true_prob, net_payout, push_prob),
            push_probability=push_prob,
            confidence_interval=confidence_interval,
            sample_size=prop_result.sample_size,
            data_source=prop_result.data_source,
            game_id=state.get("game_id"),
            player_name=target_player or None,
            direction=direction,
            true_probability=true_prob,
            implied_probability=implied_prob,
            kelly_fraction=kelly_frac,
            trade_plan=trade_plan,
            market_type=market_type,
        )

        log.info(
            "prop_arbitrage_agent.signal_produced",
            sport=resolved_sport,
            market_type=market_type,
            ev_pct=str(ev_pct),
            kelly_frac=str(kelly_frac),
        )
        return {"ev_signal": signal, "pending_signals": [signal], "gate_reason": None}

    return prop_arbitrage_agent
