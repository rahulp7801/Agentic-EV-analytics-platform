"""
Tests for vig removal probability converter (QUANT-02).

Covers: american_to_raw_prob, remove_vig_multiplicative, remove_vig_power.
All arithmetic must use Decimal — zero float leakage into return values.
"""
import pytest
from decimal import Decimal

from sportsbet.quant.vig import (
    american_to_raw_prob,
    remove_vig_multiplicative,
    remove_vig_power,
)


def test_american_to_raw_prob_negative():
    """american_to_raw_prob(-110) is within 0.000001 of Decimal('0.523809')."""
    result = american_to_raw_prob(-110)
    assert abs(result - Decimal("0.523809")) < Decimal("0.000001")


def test_american_to_raw_prob_positive():
    """american_to_raw_prob(150) == Decimal('0.4')."""
    result = american_to_raw_prob(150)
    assert result == Decimal("0.4")


def test_american_to_raw_prob_returns_decimal():
    """Return type must be Decimal, not float."""
    result = american_to_raw_prob(-110)
    assert isinstance(result, Decimal)


def test_multiplicative_sums_to_one():
    """remove_vig_multiplicative on symmetric -110/-110 market sums to Decimal('1')."""
    p = american_to_raw_prob(-110)
    fair = remove_vig_multiplicative([p, p])
    assert sum(fair) == Decimal("1")


def test_multiplicative_favorite_greater_than_half():
    """remove_vig_multiplicative on -200/+170 market: favorite prob > 0.5."""
    fav = american_to_raw_prob(-200)
    dog = american_to_raw_prob(170)
    fair = remove_vig_multiplicative([fav, dog])
    assert fair[0] > Decimal("0.5")


def test_multiplicative_overround_guard():
    """remove_vig_multiplicative raises ValueError when overround <= 1 (corrupt input)."""
    # overround = 0.4 + 0.4 = 0.8 < 1 — invalid market
    with pytest.raises(ValueError):
        remove_vig_multiplicative([Decimal("0.4"), Decimal("0.4")])


def test_power_sums_to_one():
    """remove_vig_power on symmetric -110/-110 market sums within Decimal('1e-6') of Decimal('1')."""
    p = american_to_raw_prob(-110)
    fair = remove_vig_power([p, p])
    assert abs(sum(fair) - Decimal("1")) < Decimal("1e-6")


def test_power_returns_decimals():
    """All values returned by remove_vig_power must be Decimal instances."""
    p = american_to_raw_prob(-110)
    fair = remove_vig_power([p, p])
    assert all(isinstance(v, Decimal) for v in fair)


def test_power_favors_favorite():
    """Power method assigns higher prob to favorite than multiplicative (corrects longshot bias)."""
    fav = american_to_raw_prob(-200)
    dog = american_to_raw_prob(170)

    mult = remove_vig_multiplicative([fav, dog])
    power = remove_vig_power([fav, dog])

    # Power corrects longshot bias: favorite gets more weight than multiplicative
    assert power[0] > mult[0], (
        f"Power method should increase favorite probability vs multiplicative. "
        f"Got power={power[0]}, mult={mult[0]}"
    )
