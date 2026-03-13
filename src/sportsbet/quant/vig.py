"""
Vig removal probability converter (QUANT-02).

Converts raw American odds to fair implied probabilities using two devig methods:
  - Multiplicative: proportional normalization by overround (standard)
  - Power/Pinnacle: binary-search exponent that corrects favorite-longshot bias

All probability arithmetic uses Decimal throughout to preserve precision
downstream in the Kelly Criterion pipeline. The float() cast inside
remove_vig_power is used only for the binary search convergence loop
and never appears in return values.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence


def american_to_raw_prob(american_odds: int) -> Decimal:
    """Convert American odds integer to vig-inclusive implied probability.

    Returns a Decimal constructed from strings — never from floats — to
    avoid IEEE-754 precision artifacts propagating into downstream math.

    Args:
        american_odds: American moneyline integer, e.g. -110 or +150.

    Returns:
        Vig-inclusive implied probability as Decimal.

    Examples:
        >>> american_to_raw_prob(-110)
        Decimal('0.5238095238095238095238095238')
        >>> american_to_raw_prob(150)
        Decimal('0.4')
    """
    odds = Decimal(str(american_odds))
    if american_odds < 0:
        abs_odds = abs(odds)
        return abs_odds / (abs_odds + Decimal("100"))
    else:
        return Decimal("100") / (odds + Decimal("100"))


def remove_vig_multiplicative(raw_probs: Sequence[Decimal]) -> list[Decimal]:
    """Proportional devig: normalize each raw probability by the overround total.

    This is the standard market normalization approach. It scales all implied
    probabilities proportionally so they sum to exactly 1.0. It does NOT
    correct for favorite-longshot bias — use remove_vig_power for that.

    Args:
        raw_probs: Sequence of vig-inclusive probabilities as Decimal.
                   Typical market input: [american_to_raw_prob(-110),
                   american_to_raw_prob(-110)] for a symmetric market.

    Returns:
        List of fair probabilities (Decimal) summing to exactly Decimal('1').

    Raises:
        ValueError: If overround <= 1. Both-positive-odds markets (e.g.
                    +150/+130) have overround < 1 — they represent invalid
                    input for devigging and must be rejected before any
                    division to prevent silent garbage output.

    Examples:
        >>> p = american_to_raw_prob(-110)
        >>> remove_vig_multiplicative([p, p])
        [Decimal('0.5'), Decimal('0.5')]
    """
    overround = sum(raw_probs, Decimal("0"))
    if overround <= Decimal("1"):
        raise ValueError(
            f"Invalid market: overround {overround} <= 1. "
            "Both-positive-odds markets cannot be devigged multiplicatively."
        )
    fair = [p / overround for p in raw_probs]
    # Correct accumulated rounding error on the final element so that
    # sum(fair) == Decimal("1") exactly. Error is always sub-ulp for <=20 outcomes.
    residual = Decimal("1") - sum(fair[:-1], Decimal("0"))
    fair[-1] = residual
    return fair


def remove_vig_power(
    raw_probs: Sequence[Decimal],
    tol: Decimal = Decimal("1e-9"),
) -> list[Decimal]:
    """Power (Pinnacle/sharp) devig: find exponent k in (0, 1] such that sum(p_i^k) == 1.

    Corrects favorite-longshot bias that multiplicative normalization ignores.
    Uses 60 iterations of binary search — each iteration halves the error,
    giving precision well below 1e-9 (2^-60 ≈ 8.7e-19).

    The float() cast is confined to the binary search convergence loop only.
    The final exponent k and all returned probabilities are Decimal.

    Args:
        raw_probs: Sequence of vig-inclusive probabilities as Decimal.
        tol: Convergence tolerance (unused directly — 60 iterations always
             suffice, kept as API parameter for future callers).

    Returns:
        List of fair probabilities (Decimal) summing to within 1e-9 of
        Decimal('1'). Corrected probabilities shift weight toward the
        favorite relative to multiplicative devig.

    Examples:
        >>> p = american_to_raw_prob(-110)
        >>> probs = remove_vig_power([p, p])
        >>> abs(sum(probs) - Decimal('1')) < Decimal('1e-6')
        True
    """
    # Binary search for k >= 1 such that sum(p_i^k) == 1.
    # For raw probabilities p in (0,1): increasing k decreases p^k.
    # Typical overround is 1.03–1.10 (standard market), so k is slightly above 1.0.
    # When sum > 1.0 (p^k values too large), increase k → lo = mid.
    # When sum < 1.0 (p^k values too small), decrease k → hi = mid.
    # Upper bound: k=20 is far beyond any real market overround.
    lo, hi = 1.0, 20.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        total = sum(float(p) ** mid for p in raw_probs)
        if total > 1.0:
            lo = mid
        else:
            hi = mid
    k = Decimal(str((lo + hi) / 2.0))
    return [p ** k for p in raw_probs]
