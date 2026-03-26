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
from typing import Any

import structlog

from sportsbet.arbitrage.ev import build_trade_plan, compute_ev_percentage
from sportsbet.arbitrage.kelly import fractional_kelly
from sportsbet.config import settings as _settings
from sportsbet.graph.models import EVSignal, PropResult
from sportsbet.graph.state import GraphState

log = structlog.get_logger()

_NO_SIGNAL: dict[str, Any] = {"ev_signal": None}

# Alias map: PropParams Literal shorthand -> Odds API market key format.
# Used by prop_arbitrage_agent to match state["prop_type"] against
# PlayerPropSnapshotCreate.prop_type (which stores raw Odds API market keys).
# (Phase 23 — PROP-06)
_PROP_TYPE_ALIAS_MAP: dict[str, str] = {
    "pass_yds": "player_pass_yards",
    "rush_yds": "player_rush_yards",
    "rec_yds": "player_receiving_yards",
    "pass_tds": "player_pass_tds",
    "receptions": "player_receptions",
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "pra": "player_pra",
}


def _build_prop_trade_plan(
    ev_pct: Decimal,
    kelly_frac: Decimal,
    injury_flags: dict[str, str],
    market_type: str,
    prop_result: PropResult,
) -> list[str]:
    """Build a 3-bullet prop-specific trade plan thesis.

    Bullet 1: EV edge on the specific prop market.
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
        Carries sample_size and mean_stat for bullet 2 context.

    Returns
    -------
    list[str]
        Exactly 3 non-empty strings describing edge, sizing, and context.
    """
    # Bullet 1: quantitative EV edge on the specific prop market
    bullet_1 = f"+{float(ev_pct):.1%} EV edge on {market_type} prop market"

    # Bullet 2: Kelly sizing rationale with prop-specific sample and mean
    sample = prop_result.sample_size if prop_result.sample_size is not None else "N/A"
    mean = (
        f"{float(prop_result.mean_stat):.1f}"
        if prop_result.mean_stat is not None
        else "N/A"
    )
    bullet_2 = (
        f"Kelly sizing: {float(kelly_frac):.1%} fractional stake "
        f"(n={sample}, historical mean={mean}, bankroll-relative)"
    )

    # Bullet 3: injury/weather context
    if injury_flags:
        flagged = ", ".join(
            f"{player} ({status})" for player, status in injury_flags.items()
        )
        bullet_3 = f"Material injury flags: {flagged}"
    else:
        bullet_3 = "No material injury flags for this game"

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

        # Guard 1: prop_result must exist with a real probability
        if prop_result is None or prop_result.true_probability is None:
            log.info(
                "prop_arbitrage_agent.no_prop_result",
                sport=resolved_sport,
                reason="prop_result is None or true_probability is None",
            )
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

        matched_snapshot = None
        if snapshots:
            for snap in snapshots:
                type_match = snap.prop_type == normalized_prop_type
                line_match = (target_line is None) or (snap.line == target_line)
                if type_match and line_match:
                    matched_snapshot = snap
                    break

        # Determine implied_prob, market_type, injury_flags from matched snapshot or fallback
        context_signals = state.get("context_signals")  # type: ignore[attr-defined]
        if matched_snapshot is not None:
            implied_prob: Decimal = matched_snapshot.implied_probability
            market_type: str = matched_snapshot.prop_type
            injury_flags: dict[str, str] = (
                context_signals.injury_flags
                if context_signals is not None
                else {}
            )
        else:
            # Guard 2b: fall back to context_signals.odds_snapshot (non-prop or snapshot-missing routes)
            if context_signals is None or context_signals.odds_snapshot is None:
                log.info(
                    "prop_arbitrage_agent.no_prop_snapshot",
                    sport=resolved_sport,
                    prop_type=target_prop_type,
                    prop_line=str(raw_line),
                    reason="no matching PlayerPropSnapshot found in state and no odds_snapshot fallback",
                )
                return _NO_SIGNAL
            snapshot = context_signals.odds_snapshot
            implied_prob = snapshot.implied_probability
            market_type = snapshot.market_type
            injury_flags = context_signals.injury_flags

        true_prob: Decimal = prop_result.true_probability

        # EV computation — floored at 0
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

        # Kelly sizing — Decimal(str(...)) pattern locked in Phase 2
        kelly_frac = fractional_kelly(
            p=true_prob,
            b=Decimal("1.0"),
            fraction=Decimal(str(cfg.max_kelly_fraction)),
        )

        # 3-bullet prop-aware trade plan
        trade_plan = _build_prop_trade_plan(
            ev_pct, kelly_frac, injury_flags, market_type, prop_result
        )

        signal = EVSignal(
            ev_percentage=ev_pct,
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
        return {"ev_signal": signal, "pending_signals": [signal]}

    return prop_arbitrage_agent
