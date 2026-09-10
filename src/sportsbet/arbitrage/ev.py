"""EV (expected value) computation and trade plan generation for the Arbitrage Agent.

EV formula used:
    ev_pct = true_probability - implied_probability

This is the simplest positive-edge signal: if our model assigns a higher
probability than the sportsbook's implied probability (which includes vig),
we have positive expected value on that market.

Floor at Decimal("0"): negative EV is suppressed entirely — the Arbitrage Agent
must never surface a -EV signal. EVSignal.ev_percentage is also constrained
gt=Decimal("0") at the Pydantic model level; this function prevents callers from
accidentally passing a zero-or-negative value to the model.

Trade Plan contract:
- Exactly 3 strings — enforced by EVSignal.trade_plan max_length=3 constraint
- Bullet 1: quantitative EV edge and market context
- Bullet 2: Kelly fraction rationale (emphasizes bankroll-relative sizing, not flat)
- Bullet 3: injury/weather context or clean bill of health
"""
from __future__ import annotations

from decimal import Decimal

from sportsbet.quant.vig import american_to_raw_prob

_ZERO = Decimal("0")


def quote_terms(american_odds: int | None, implied_probability: Decimal) -> tuple[Decimal, Decimal]:
    """Return break-even probability and net payout from the same quote.

    Raw price is authoritative when present (stored probability may be devigged).
    Legacy snapshots without price imply payout from their break-even probability.
    Synthetic provider prices remain synthetic; this does not validate their payout.
    """
    if american_odds is not None:
        if american_odds == 0:
            raise ValueError("American odds cannot be zero")
        probability = american_to_raw_prob(american_odds)
        odds = Decimal(american_odds)
        payout = Decimal("100") / abs(odds) if odds < 0 else odds / Decimal("100")
    else:
        probability = implied_probability
        if not probability.is_finite() or not _ZERO < probability < Decimal("1"):
            raise ValueError("Break-even probability must be between zero and one")
        payout = (Decimal("1") - probability) / probability
    return probability, payout


def compute_expected_return(true_prob: Decimal, net_payout: Decimal) -> Decimal:
    """Expected profit per unit staked for a binary market with no push mass.

    Unlike legacy compute_ev_percentage (probability edge), negative returns
    are preserved. Integer lines with possible pushes need separate settlement.
    """
    return true_prob * net_payout - (Decimal("1") - true_prob)


def compute_ev_percentage(true_prob: Decimal, implied_prob: Decimal) -> Decimal:
    """Compute positive EV percentage as (true_prob - implied_prob), floored at 0.

    Parameters
    ----------
    true_prob : Decimal
        Model-derived win probability from QuantResult.
    implied_prob : Decimal
        Sportsbook-implied probability from AgentOddsSnapshot (includes vig).

    Returns
    -------
    Decimal
        Positive edge as a Decimal fraction. Returns Decimal("0") when the
        sportsbook's implied probability meets or exceeds the model probability
        (no exploitable edge exists).

    Examples
    --------
    >>> compute_ev_percentage(Decimal("0.65"), Decimal("0.55"))
    Decimal('0.10')
    >>> compute_ev_percentage(Decimal("0.50"), Decimal("0.55"))
    Decimal('0')
    """
    ev = true_prob - implied_prob
    return max(_ZERO, ev)


def build_trade_plan(
    ev_pct: Decimal,
    kelly_frac: Decimal,
    injury_flags: dict[str, str],
    market_type: str,
) -> list[str]:
    """Build a 3-bullet trade plan thesis for an EVSignal.

    The returned list has exactly 3 non-empty strings matching CLAUDE.md's
    "maximum 3 bullet points" actionable thesis requirement and EVSignal's
    trade_plan max_length=3 constraint.

    Parameters
    ----------
    ev_pct : Decimal
        Positive EV percentage (from compute_ev_percentage).
    kelly_frac : Decimal
        Fractional Kelly stake as bankroll fraction (from fractional_kelly).
    injury_flags : dict[str, str]
        Player-to-status mapping from ContextSignals.injury_flags.
        Empty dict → clean bill of health bullet.
    market_type : str
        Market identifier from AgentOddsSnapshot (e.g. "h2h", "spreads").

    Returns
    -------
    list[str]
        Exactly 3 non-empty strings describing edge, sizing, and context.

    Notes
    -----
    Float conversion is used only for display formatting (f-string % format spec).
    All Decimal arithmetic performed prior to this function stays pure Decimal.
    """
    # Bullet 1: quantitative edge on the specific market
    bullet_1 = f"+{float(ev_pct):.1%} EV edge on {market_type} market"

    # Bullet 2: Kelly sizing rationale — explicitly non-flat
    bullet_2 = f"Kelly sizing: {float(kelly_frac):.1%} fractional stake (bankroll-relative, not flat)"

    # Bullet 3: injury/weather context
    if injury_flags:
        flagged = ", ".join(
            f"{player} ({status})"
            for player, status in injury_flags.items()
        )
        bullet_3 = f"Material injury flags: {flagged}"
    else:
        bullet_3 = "No material injury flags for this game"

    return [bullet_1, bullet_2, bullet_3]
