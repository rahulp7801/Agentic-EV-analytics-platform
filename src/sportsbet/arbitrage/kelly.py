"""Fractional Kelly Criterion sizing for the Arbitrage Agent.

The Kelly formula sizes a bet as a fraction of bankroll to maximize
long-run geometric growth. Full Kelly is theoretically optimal but
highly volatile in practice; this module implements fractional Kelly
(multiply f* by a fraction) and enforces a hard cap at 25% of bankroll.

References:
- Kelly (1956): "A New Interpretation of Information Rate"
- Thorp (1962): "Beat the Dealer" — fractional Kelly popularized

Design rules (from CLAUDE.md prop firm standards):
- All arithmetic uses Decimal — never float, never int-to-Decimal cast
- Hard cap at Decimal("0.25") — enforced here AND by EVSignal Field constraint
- Floor at Decimal("0") — negative Kelly means no bet, never short sizing
"""
from __future__ import annotations

from decimal import Decimal

_CAP = Decimal("0.25")
_ZERO = Decimal("0")


def fractional_kelly(p: Decimal, b: Decimal, fraction: Decimal) -> Decimal:
    """Compute fractional Kelly bet size as a bankroll fraction.

    Formula:
        f* = (b * p - (1 - p)) / b
        result = f* * fraction
        result = max(0, min(0.25, result))

    Parameters
    ----------
    p : Decimal
        True win probability in [0, 1].
    b : Decimal
        Decimal odds of the bet (net profit per unit stake).
        For moneyline even-money markets use Decimal("1.0").
    fraction : Decimal
        Fractional Kelly multiplier, typically Settings.max_kelly_fraction.
        Use Decimal("1.0") for full Kelly (discouraged per CLAUDE.md).

    Returns
    -------
    Decimal
        Bankroll fraction to stake, in [0, 0.25].
        Returns Decimal("0") for negative-EV situations.

    Examples
    --------
    >>> fractional_kelly(Decimal("0.60"), Decimal("1.0"), Decimal("0.5"))
    Decimal('0.10')
    >>> fractional_kelly(Decimal("0.90"), Decimal("1.0"), Decimal("1.0"))
    Decimal('0.25')
    >>> fractional_kelly(Decimal("0.40"), Decimal("1.0"), Decimal("0.5"))
    Decimal('0')
    """
    q = Decimal("1") - p
    f_star = (b * p - q) / b
    result = f_star * fraction
    return max(_ZERO, min(_CAP, result))
