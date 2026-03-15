"""Tests for Phase 5 Plan 01: Arbitrage subpackage — Kelly, EV, make_arbitrage_agent.

RED phase: tests are written before implementation — ImportError / AssertionError expected.
GREEN phase: all 8 tests pass after kelly.py, ev.py, and make_arbitrage_agent are implemented.

Test inventory:
1. test_fractional_kelly_standard         — fractional_kelly standard case, no cap
2. test_fractional_kelly_cap              — raw f*=0.80 hard-capped at Decimal("0.25")
3. test_fractional_kelly_negative_ev      — p=0.40 → negative raw f* clipped to Decimal("0")
4. test_compute_ev_percentage_positive    — positive EV returns positive Decimal
5. test_compute_ev_no_edge                — implied >= true → returns Decimal("0")
6. test_build_trade_plan_length           — build_trade_plan returns exactly 3 non-empty strings
7. test_arbt01_ev_signal_produced         — make_arbitrage_agent returns EVSignal when edge > 0
8. test_arbt02_kelly_fraction_non_flat    — EVSignal.kelly_fraction > 0 and <= Decimal("0.25")
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

try:
    from sportsbet.arbitrage.kelly import fractional_kelly
    _KELLY_IMPORTED = True
except ImportError:
    fractional_kelly = None  # type: ignore[assignment]
    _KELLY_IMPORTED = False

try:
    from sportsbet.arbitrage.ev import build_trade_plan, compute_ev_percentage
    _EV_IMPORTED = True
except ImportError:
    compute_ev_percentage = None  # type: ignore[assignment]
    build_trade_plan = None  # type: ignore[assignment]
    _EV_IMPORTED = False

try:
    from sportsbet.graph.agents import make_arbitrage_agent
    _AGENT_IMPORTED = True
except ImportError:
    make_arbitrage_agent = None  # type: ignore[assignment]
    _AGENT_IMPORTED = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_state(true_prob: Decimal, implied_prob: Decimal, quant_result_none: bool = False):
    """Build a minimal GraphState-compatible dict for arbitrage agent tests."""
    from datetime import datetime, timezone

    from sportsbet.graph.models import AgentOddsSnapshot, ContextSignals, QuantResult

    if quant_result_none:
        quant_result = None
    else:
        quant_result = QuantResult(
            true_probability=true_prob,
            sample_size=45,
            data_source="test",
        )

    odds_snapshot = AgentOddsSnapshot(
        game_id="2025_01_KC_LAC",
        sportsbook="draftkings",
        market_type="h2h",
        implied_probability=implied_prob,
        snapped_at=datetime.now(timezone.utc),
    )
    context_signals = ContextSignals(
        game_id="2025_01_KC_LAC",
        injury_flags={},
        weather_json=None,
        odds_snapshot=odds_snapshot,
        signals_captured_at=datetime.now(timezone.utc),
    )

    return {
        "session_id": "test-session-001",
        "request_type": "odds_check",
        "created_at": datetime.now(timezone.utc),
        "game_id": "2025_01_KC_LAC",
        "season": 2025,
        "week": 1,
        "home_team": "KC",
        "away_team": "LAC",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": quant_result,
        "ev_signal": None,
        "context_signals": context_signals,
    }


# ---------------------------------------------------------------------------
# Test 1: fractional_kelly standard case
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _KELLY_IMPORTED, reason="sportsbet.arbitrage.kelly not yet implemented")
def test_fractional_kelly_standard():
    """f* = (1.0*0.60 - 0.40)/1.0 = 0.20; * 0.5 fraction = 0.10."""
    result = fractional_kelly(
        p=Decimal("0.60"),
        b=Decimal("1.0"),
        fraction=Decimal("0.5"),
    )
    assert result == Decimal("0.10"), f"Expected Decimal('0.10'), got {result!r}"


# ---------------------------------------------------------------------------
# Test 2: fractional_kelly hard cap at 0.25
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _KELLY_IMPORTED, reason="sportsbet.arbitrage.kelly not yet implemented")
def test_fractional_kelly_cap():
    """p=0.90, b=1.0, fraction=1.0 → raw f*=0.80 → capped at Decimal('0.25')."""
    result = fractional_kelly(
        p=Decimal("0.90"),
        b=Decimal("1.0"),
        fraction=Decimal("1.0"),
    )
    assert result == Decimal("0.25"), f"Expected Decimal('0.25'), got {result!r}"


# ---------------------------------------------------------------------------
# Test 3: fractional_kelly negative EV clipped to zero
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _KELLY_IMPORTED, reason="sportsbet.arbitrage.kelly not yet implemented")
def test_fractional_kelly_negative_ev():
    """p=0.40, b=1.0 → raw f*=(0.40-0.60)/1.0=-0.20 → floored at Decimal('0')."""
    result = fractional_kelly(
        p=Decimal("0.40"),
        b=Decimal("1.0"),
        fraction=Decimal("0.5"),
    )
    assert result == Decimal("0"), f"Expected Decimal('0'), got {result!r}"


# ---------------------------------------------------------------------------
# Test 4: compute_ev_percentage positive case
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EV_IMPORTED, reason="sportsbet.arbitrage.ev not yet implemented")
def test_compute_ev_percentage_positive():
    """true_prob=0.65 > implied_prob=0.55 → positive Decimal edge."""
    result = compute_ev_percentage(Decimal("0.65"), Decimal("0.55"))
    assert result > Decimal("0"), f"Expected positive EV, got {result!r}"
    # ev = 0.65 - 0.55 = 0.10
    assert result == Decimal("0.10"), f"Expected Decimal('0.10'), got {result!r}"


# ---------------------------------------------------------------------------
# Test 5: compute_ev_percentage no edge (clipped to zero)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EV_IMPORTED, reason="sportsbet.arbitrage.ev not yet implemented")
def test_compute_ev_no_edge():
    """true_prob=0.50 < implied_prob=0.55 → negative EV clipped to Decimal('0')."""
    result = compute_ev_percentage(Decimal("0.50"), Decimal("0.55"))
    assert result == Decimal("0"), f"Expected Decimal('0'), got {result!r}"


# ---------------------------------------------------------------------------
# Test 6: build_trade_plan returns exactly 3 non-empty strings
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EV_IMPORTED, reason="sportsbet.arbitrage.ev not yet implemented")
def test_build_trade_plan_length():
    """build_trade_plan must return a list of exactly 3 non-empty strings."""
    plan = build_trade_plan(
        ev_pct=Decimal("0.10"),
        kelly_frac=Decimal("0.05"),
        injury_flags={"P. Mahomes": "Questionable"},
        market_type="h2h",
    )
    assert isinstance(plan, list), f"Expected list, got {type(plan)}"
    assert len(plan) == 3, f"Expected 3 bullets, got {len(plan)}"
    for i, bullet in enumerate(plan):
        assert isinstance(bullet, str), f"Bullet {i} is not str: {bullet!r}"
        assert len(bullet) > 0, f"Bullet {i} is empty"


# ---------------------------------------------------------------------------
# Test 7: make_arbitrage_agent returns EVSignal when edge > 0 (ARBT-01)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _AGENT_IMPORTED, reason="make_arbitrage_agent not yet implemented")
def test_arbt01_ev_signal_produced():
    """make_arbitrage_agent()(state) returns {'ev_signal': EVSignal} with positive edge."""
    import asyncio

    from sportsbet.graph.models import EVSignal

    state = _make_state(true_prob=Decimal("0.65"), implied_prob=Decimal("0.55"))
    agent = make_arbitrage_agent()
    result = asyncio.run(agent(state))

    assert "ev_signal" in result, f"'ev_signal' key missing from result: {result}"
    signal = result["ev_signal"]
    assert signal is not None, "ev_signal should not be None for positive EV"
    assert isinstance(signal, EVSignal), f"Expected EVSignal, got {type(signal)}"
    assert signal.ev_percentage > Decimal("0"), f"ev_percentage must be positive, got {signal.ev_percentage}"


# ---------------------------------------------------------------------------
# Test 8: EVSignal.kelly_fraction is bankroll fraction, never flat dollar (ARBT-02)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _AGENT_IMPORTED, reason="make_arbitrage_agent not yet implemented")
def test_arbt02_kelly_fraction_non_flat():
    """EVSignal.kelly_fraction must be a Decimal fraction in (0, 0.25]."""
    import asyncio

    state = _make_state(true_prob=Decimal("0.65"), implied_prob=Decimal("0.55"))
    agent = make_arbitrage_agent()
    result = asyncio.run(agent(state))

    signal = result["ev_signal"]
    assert signal is not None
    assert isinstance(signal.kelly_fraction, Decimal), (
        f"kelly_fraction must be Decimal, got {type(signal.kelly_fraction)}"
    )
    assert signal.kelly_fraction > Decimal("0"), (
        f"kelly_fraction must be > 0, got {signal.kelly_fraction}"
    )
    assert signal.kelly_fraction <= Decimal("0.25"), (
        f"kelly_fraction must be <= 0.25 (hard cap), got {signal.kelly_fraction}"
    )
