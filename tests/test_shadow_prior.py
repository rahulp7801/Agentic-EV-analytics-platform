import pytest

from sportsbet.quant.shadow_prior import prior80_conditional_probability


def test_prior80_recovers_recorded_jeffreys_wins():
    forecast = dict(model_version='empirical-jeffreys-v4', model_sample_size=20,
                    model_probability=.738095, push_probability=0)
    assert prior80_conditional_probability(forecast) == pytest.approx(55/100)


def test_prior80_conditions_on_no_push_and_rejects_non_v4():
    forecast = dict(model_version='empirical-jeffreys-v4', model_sample_size=20,
                    model_probability=.4921875, push_probability=.25)
    assert prior80_conditional_probability(forecast) == pytest.approx(50/95)
    assert prior80_conditional_probability({**forecast, 'model_version':'future-v5'}) is None
    assert prior80_conditional_probability({**forecast, 'model_probability':.6}) is None
