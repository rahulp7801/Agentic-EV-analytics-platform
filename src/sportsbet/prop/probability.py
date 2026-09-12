"""Finite-sample probabilities for Over/Under props with explicit pushes."""
from __future__ import annotations

from decimal import Decimal

from statsmodels.stats.proportion import proportion_confint

_HALF = Decimal("0.5")
_ONE = Decimal(1)


def empirical_outcome_probabilities(
    successes: int,
    pushes: int,
    total: int,
) -> tuple[Decimal, Decimal, tuple[Decimal, Decimal]]:
    """Return unconditional Over, push, and Over interval probabilities.

    Push mass is observed directly. The Over probability conditional on a decided
    outcome uses the Jeffreys Beta(1/2, 1/2) posterior predictive mean, avoiding
    unjustified zero and one forecasts. The Wilson interval is computed over the
    same decided outcomes and then scaled back to unconditional probability mass.
    """
    if any(type(value) is not int for value in (successes, pushes, total)):
        raise TypeError("Outcome counts must be integers")
    if total <= 0 or successes < 0 or pushes < 0 or successes + pushes > total:
        raise ValueError("Invalid outcome counts")
    decided = total - pushes
    if decided == 0:
        raise ValueError("No decided outcomes")

    total_decimal = Decimal(total)
    non_push = Decimal(decided) / total_decimal
    push_probability = Decimal(pushes) / total_decimal
    conditional_over = (Decimal(successes) + _HALF) / (Decimal(decided) + _ONE)
    over_probability = non_push * conditional_over

    lo, hi = proportion_confint(count=successes, nobs=decided, alpha=0.05, method="wilson")
    interval = (non_push * Decimal(str(lo)), non_push * Decimal(str(hi)))
    return over_probability, push_probability, interval
