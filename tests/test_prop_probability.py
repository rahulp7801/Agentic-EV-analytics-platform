from decimal import Decimal

import pytest

from sportsbet.prop.probability import empirical_outcome_probabilities, outcome_interval_for_side


def test_jeffreys_mean_avoids_extreme_finite_sample_forecasts():
    none, push, _ = empirical_outcome_probabilities(0, 0, 20)
    all_, _, _ = empirical_outcome_probabilities(20, 0, 20)
    assert none == Decimal("0.5") / Decimal(21)
    assert all_ == Decimal("20.5") / Decimal(21)
    assert push == 0


def test_push_mass_is_separate_and_probabilities_remain_coherent():
    over, push, interval = empirical_outcome_probabilities(6, 2, 10)
    under = Decimal(1) - over - push
    assert over == Decimal("5.2") / Decimal(9)
    assert push == Decimal("0.2")
    assert under == Decimal("2") / Decimal(9)
    assert Decimal(0) <= interval[0] <= over <= interval[1] <= Decimal("0.8")


@pytest.mark.parametrize("counts", [(0, 10, 10), (-1, 0, 10), (10, 1, 10), (0, 0, 0)])
def test_invalid_or_undecided_samples_are_rejected(counts):
    with pytest.raises(ValueError):
        empirical_outcome_probabilities(*counts)


def test_boolean_counts_are_rejected():
    with pytest.raises(TypeError):
        empirical_outcome_probabilities(True, 0, 20)


def test_directional_interval_complements_within_non_push_mass():
    interval = (Decimal("0.20"), Decimal("0.35"))
    assert outcome_interval_for_side(interval, Decimal("0.10"), "over") == interval
    assert outcome_interval_for_side(interval, Decimal("0.10"), "under") == (
        Decimal("0.55"), Decimal("0.70")
    )


@pytest.mark.parametrize(
    "interval,push,direction",
    [
        (None, Decimal("0"), "over"),
        ((Decimal("0.1"), Decimal("1.1")), Decimal("0"), "over"),
        ((Decimal("0.1"), Decimal("0.2")), Decimal("NaN"), "over"),
        ((Decimal("0.1"), Decimal("0.2")), Decimal("0"), "invalid"),
    ],
)
def test_invalid_directional_interval_is_unavailable(interval, push, direction):
    assert outcome_interval_for_side(interval, push, direction) is None
