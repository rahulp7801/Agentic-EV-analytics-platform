"""Frozen, untraded shrinkage challenger for empirical Jeffreys v4 forecasts.

Strength 80 was selected on the exploratory September 2026 slate. Only future,
separately timestamped games may validate it against sportsbook probabilities.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


PRIOR_STRENGTH = 80
COUNT_TOLERANCE = Decimal('0.0001')
MODEL_VERSION = 'empirical-jeffreys-v4'


def _integer_count(value: Decimal) -> int | None:
    result = int(value.to_integral_value(rounding=ROUND_HALF_UP))
    return result if abs(value-Decimal(result)) <= COUNT_TOLERANCE else None


def prior80_conditional_probability(forecast: dict) -> float | None:
    """Recover v4 success counts and return P(win | no push) with Beta(40,40)."""
    try:
        if forecast.get('model_version') != MODEL_VERSION:
            return None
        n = forecast['model_sample_size']
        if type(n) is not int or n <= 0:
            return None
        p = Decimal(str(forecast['model_probability']))
        push = Decimal(str(forecast['push_probability']))
        if not p.is_finite() or not push.is_finite() or not 0 <= p <= 1-push or not 0 <= push < 1:
            return None
        push_count = _integer_count(push*n)
        if push_count is None or not 0 <= push_count < n:
            return None
        decided = n-push_count
        jeffreys_wins = p/(1-push)*(decided+1)-Decimal('0.5')
        wins = _integer_count(jeffreys_wins)
        if wins is None or not 0 <= wins <= decided:
            return None
        return float((Decimal(wins)+Decimal(PRIOR_STRENGTH)/2)
                     /(Decimal(decided)+Decimal(PRIOR_STRENGTH)))
    except (KeyError, TypeError, ValueError, InvalidOperation, ZeroDivisionError):
        return None
