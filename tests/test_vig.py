"""
Tests for vig removal probability converter (QUANT-02).

TDD RED phase: all test bodies fail with assert False or ImportError stub.
"""
from decimal import Decimal

try:
    from sportsbet.quant.vig import (
        american_to_raw_prob,
        remove_vig_multiplicative,
        remove_vig_power,
    )
    _import_ok = True
except ImportError:
    _import_ok = False


def test_american_to_raw_prob_negative():
    """american_to_raw_prob(-110) is within 0.000001 of Decimal('0.523809')."""
    assert False, "not implemented"


def test_american_to_raw_prob_positive():
    """american_to_raw_prob(150) == Decimal('0.4')."""
    assert False, "not implemented"


def test_american_to_raw_prob_returns_decimal():
    """Return type must be Decimal, not float."""
    assert False, "not implemented"


def test_multiplicative_sums_to_one():
    """remove_vig_multiplicative on symmetric -110/-110 market sums to Decimal('1')."""
    assert False, "not implemented"


def test_multiplicative_favorite_greater_than_half():
    """remove_vig_multiplicative on -200/+170 market: favorite prob > 0.5."""
    assert False, "not implemented"


def test_multiplicative_overround_guard():
    """remove_vig_multiplicative raises ValueError when overround <= 1 (corrupt input)."""
    assert False, "not implemented"


def test_power_sums_to_one():
    """remove_vig_power on symmetric -110/-110 market sums within Decimal('1e-6') of Decimal('1')."""
    assert False, "not implemented"


def test_power_returns_decimals():
    """All values returned by remove_vig_power must be Decimal instances."""
    assert False, "not implemented"


def test_power_favors_favorite():
    """Power method assigns higher prob to favorite than multiplicative (corrects longshot bias)."""
    assert False, "not implemented"
