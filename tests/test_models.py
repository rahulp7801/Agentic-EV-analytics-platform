"""Tests for Pydantic v2 agent I/O models in sportsbet.graph.models.

TDD RED: All tests written before implementation. Run first to confirm failure.
TDD GREEN: After implementing models, all 10 tests must pass.

Covers:
- QuantParams: valid, invalid stat_type, invalid season range
- EVSignal: valid, kelly_fraction bounds, ev_percentage positive, trade_plan max 3
- AgentOddsSnapshot: implied_probability is Decimal (not int)
- GameState: valid instantiation including nullable weather_json
- QuantResult: all 4 fields can be None (stub model)
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sportsbet.graph.models import (
    AgentOddsSnapshot,
    EVSignal,
    GameState,
    QuantParams,
    QuantResult,
)


# ---------------------------------------------------------------------------
# QuantParams
# ---------------------------------------------------------------------------


def test_quant_params_valid() -> None:
    """Happy path: valid QuantParams instantiates without error."""
    params = QuantParams(
        game_id="2023_01_KC_DET",
        season=2023,
        week=1,
        posteam="KC",
        stat_type="passing",
        filters={},
    )
    assert params.game_id == "2023_01_KC_DET"
    assert params.season == 2023
    assert params.stat_type == "passing"


def test_quant_params_invalid_stat_type() -> None:
    """stat_type='kicking' is not in the allowed Literal — must raise ValidationError."""
    with pytest.raises(ValidationError):
        QuantParams(
            game_id="2023_01_KC_DET",
            season=2023,
            week=1,
            posteam="KC",
            stat_type="kicking",  # type: ignore[arg-type]
            filters={},
        )


def test_quant_params_invalid_season() -> None:
    """season below 1999 or above 2030 must raise ValidationError."""
    with pytest.raises(ValidationError):
        QuantParams(
            game_id="1998_01_SF_GB",
            season=1998,
            week=1,
            posteam="SF",
            stat_type="passing",
            filters={},
        )
    with pytest.raises(ValidationError):
        QuantParams(
            game_id="2031_01_KC_DET",
            season=2031,
            week=1,
            posteam="KC",
            stat_type="passing",
            filters={},
        )


# ---------------------------------------------------------------------------
# EVSignal
# ---------------------------------------------------------------------------


def test_ev_signal_valid() -> None:
    """Happy path: valid EVSignal instantiates without error."""
    signal = EVSignal(
        ev_percentage=Decimal("0.05"),
        true_probability=Decimal("0.55"),
        implied_probability=Decimal("0.50"),
        kelly_fraction=Decimal("0.10"),
        trade_plan=["edge1", "edge2", "edge3"],
        market_type="moneyline",
    )
    assert signal.ev_percentage == Decimal("0.05")
    assert signal.kelly_fraction == Decimal("0.10")
    assert len(signal.trade_plan) == 3


def test_ev_signal_kelly_fraction_bounds() -> None:
    """kelly_fraction > 0.25 or <= 0 must raise ValidationError."""
    base = dict(
        ev_percentage=Decimal("0.05"),
        true_probability=Decimal("0.55"),
        implied_probability=Decimal("0.50"),
        trade_plan=["edge1"],
        market_type="moneyline",
    )
    with pytest.raises(ValidationError):
        EVSignal(**base, kelly_fraction=Decimal("0.30"))  # exceeds 0.25

    with pytest.raises(ValidationError):
        EVSignal(**base, kelly_fraction=Decimal("0"))  # must be > 0


def test_ev_signal_ev_percentage_positive() -> None:
    """ev_percentage <= 0 must raise ValidationError."""
    with pytest.raises(ValidationError):
        EVSignal(
            ev_percentage=Decimal("-0.01"),
            true_probability=Decimal("0.55"),
            implied_probability=Decimal("0.50"),
            kelly_fraction=Decimal("0.10"),
            trade_plan=["edge1"],
            market_type="moneyline",
        )


def test_ev_signal_trade_plan_max_3() -> None:
    """trade_plan with 4 items must raise ValidationError."""
    with pytest.raises(ValidationError):
        EVSignal(
            ev_percentage=Decimal("0.05"),
            true_probability=Decimal("0.55"),
            implied_probability=Decimal("0.50"),
            kelly_fraction=Decimal("0.10"),
            trade_plan=["a", "b", "c", "d"],  # 4 items — exceeds max
            market_type="moneyline",
        )


# ---------------------------------------------------------------------------
# AgentOddsSnapshot
# ---------------------------------------------------------------------------


def test_agent_odds_snapshot_has_decimal_probability() -> None:
    """implied_probability must be stored as Decimal, not an int."""
    snapshot = AgentOddsSnapshot(
        game_id="2023_01_KC_DET",
        sportsbook="draftkings",
        market_type="moneyline",
        implied_probability=Decimal("0.5238"),
        snapped_at=datetime(2023, 9, 7, 20, 0, 0, tzinfo=timezone.utc),
    )
    assert isinstance(snapshot.implied_probability, Decimal)
    # strict=True: passing an int where Decimal is expected must fail
    with pytest.raises(ValidationError):
        AgentOddsSnapshot(
            game_id="2023_01_KC_DET",
            sportsbook="draftkings",
            market_type="moneyline",
            implied_probability=1,  # type: ignore[arg-type]  # int, not Decimal
            snapped_at=datetime(2023, 9, 7, 20, 0, 0, tzinfo=timezone.utc),
        )


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------


def test_game_state_valid() -> None:
    """GameState instantiates with all fields, including nullable weather_json."""
    state = GameState(
        game_id="2023_01_KC_DET",
        season=2023,
        week=1,
        home_team="DET",
        away_team="KC",
        injury_flags={"Patrick Mahomes": "Questionable"},
        weather_json={"temp_f": 72, "wind_mph": 5, "condition": "Clear"},
    )
    assert state.weather_json is not None
    assert state.injury_flags["Patrick Mahomes"] == "Questionable"

    # weather_json can be None
    state_no_weather = GameState(
        game_id="2023_01_KC_DET",
        season=2023,
        week=1,
        home_team="DET",
        away_team="KC",
        injury_flags={},
        weather_json=None,
    )
    assert state_no_weather.weather_json is None


# ---------------------------------------------------------------------------
# QuantResult
# ---------------------------------------------------------------------------


def test_quant_result_all_fields_nullable() -> None:
    """QuantResult is a stub — all 4 fields default to None."""
    result = QuantResult()
    assert result.true_probability is None
    assert result.sample_size is None
    assert result.confidence_interval is None
    assert result.data_source is None
