"""Hand-calculated quote/side regressions; no database or live odds required."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsbet.config import Settings
from sportsbet.graph.agents import make_arbitrage_agent
from sportsbet.graph.models import AgentOddsSnapshot, ContextSignals, PropResult, QuantResult
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.quant.vig import american_to_raw_prob


def quote(price=-110, side="Over", player="Test Player"):
    return PlayerPropSnapshotCreate(
        sport="nba", player_name=player, sportsbook="testbook",
        prop_type="player_points", line=Decimal("20.5"), price=price,
        implied_probability=american_to_raw_prob(price), side=side,
    )


@pytest.mark.parametrize("price,expected", [(-110, "0.04"), (120, "0.06666666666666666666666666667")])
@pytest.mark.parametrize("prop_agent", [True, False])
async def test_actual_payout_sizes_kelly(price, expected, prop_agent):
    cfg = Settings(_env_file=None, max_kelly_fraction=0.25)
    state = {
        "session_id": "pricing", "player_name": "Test Player",
        "prop_type": "points", "prop_line": Decimal("20.5"),
        "nba_prop_result": PropResult(true_probability=Decimal("0.6"), sample_size=50),
        "quant_result": QuantResult(prediction_target="market_outcome", true_probability=Decimal("0.6")),
        "player_prop_snapshots": [quote(price)],
    }
    agent = make_prop_arbitrage_agent(sport="nba", settings_override=cfg) if prop_agent else make_arbitrage_agent(cfg)
    signal = (await agent(state))["ev_signal"]
    assert signal is not None
    assert float(signal.kelly_fraction) == pytest.approx(float(expected))
    assert float(signal.expected_return) == pytest.approx(0.16 / 1.1 if price == -110 else 0.32)


async def test_prop_never_uses_under_quote_for_over_probability():
    state = {
        "player_name": "Test Player", "prop_type": "points", "prop_line": Decimal("20.5"),
        "nba_prop_result": PropResult(true_probability=Decimal("0.6"), sample_size=50),
        "player_prop_snapshots": [quote(-150, "Under"), quote(-110)],
    }
    signal = (await make_prop_arbitrage_agent(sport="nba")(state))["ev_signal"]
    assert signal is not None
    assert signal.implied_probability == american_to_raw_prob(-110)


async def test_negative_return_quote_cannot_produce_positive_kelly():
    # Deliberately stale implied probability must not override the actual -200 price.
    snap = quote(-200).model_copy(update={"implied_probability": Decimal("0.5")})
    state = {"player_name": "Test Player", "prop_type": "points", "prop_line": Decimal("20.5"),
             "nba_prop_result": PropResult(true_probability=Decimal("0.6"), sample_size=50),
             "player_prop_snapshots": [snap]}
    assert (await make_prop_arbitrage_agent(sport="nba")(state))["ev_signal"] is None


async def test_context_quote_uses_actual_odds_not_devigged_probability():
    now = datetime.now(timezone.utc)
    state = {"session_id": "pricing", "quant_result": QuantResult(prediction_target="market_outcome", true_probability=Decimal("0.6")),
             "context_signals": ContextSignals(game_id="game", signals_captured_at=now, injury_flags={},
                 odds_snapshot=AgentOddsSnapshot(game_id="game", sportsbook="testbook",
                     market_type="h2h", american_odds=-110, implied_probability=Decimal("0.5"),
                     snapped_at=now))}
    signal = (await make_arbitrage_agent()(state))["ev_signal"]
    assert signal is not None
    assert float(signal.kelly_fraction) == pytest.approx(0.04)
    assert signal.implied_probability == american_to_raw_prob(-110)


def test_scanner_under_uses_shared_cap_and_actual_payout():
    import runpy
    from pathlib import Path

    scanner = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scan_game_ev.py"))
    assert scanner["_under_kelly"](0.6, -110) == pytest.approx(0.04)
    assert scanner["_under_kelly"](0.99, 100, 1.0) == 0.25


@pytest.mark.parametrize("price,probability", [(0, Decimal("0.5")), (None, Decimal("0")), (None, Decimal("1"))])
def test_invalid_quote_terms_rejected(price, probability):
    from sportsbet.arbitrage.ev import quote_terms

    with pytest.raises(ValueError):
        quote_terms(price, probability)
