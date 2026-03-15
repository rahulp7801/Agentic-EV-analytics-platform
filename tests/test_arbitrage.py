"""Tests for Phase 5 Plans 01 and 02: Arbitrage subpackage — Kelly, EV, make_arbitrage_agent,
CorrelationGuard, and Aggregator.

RED phase: tests are written before implementation — ImportError / AssertionError expected.
GREEN phase: all tests pass after implementation.

Test inventory (Plan 01 — ARBT-01, ARBT-02):
1. test_fractional_kelly_standard         — fractional_kelly standard case, no cap
2. test_fractional_kelly_cap              — raw f*=0.80 hard-capped at Decimal("0.25")
3. test_fractional_kelly_negative_ev      — p=0.40 → negative raw f* clipped to Decimal("0")
4. test_compute_ev_percentage_positive    — positive EV returns positive Decimal
5. test_compute_ev_no_edge                — implied >= true → returns Decimal("0")
6. test_build_trade_plan_length           — build_trade_plan returns exactly 3 non-empty strings
7. test_arbt01_ev_signal_produced         — make_arbitrage_agent returns EVSignal when edge > 0
8. test_arbt02_kelly_fraction_non_flat    — EVSignal.kelly_fraction > 0 and <= Decimal("0.25")

Test inventory (Plan 02 — ARBT-03: CorrelationGuard):
9.  test_arbt03_conflict_blocked          — both signals blocked when market_types form a CONFLICT_PAIR
10. test_arbt03_no_conflict_passes        — non-conflicting single signal passes through unchanged
11. test_arbt03_conflict_pairs_defined    — CONFLICT_PAIRS contains over_passing_yards/under_total_points pair
12. test_arbt03_partial_conflict          — only conflicting pair blocked; unrelated signal passes through

Test inventory (Plan 02 — ARBT-04: Aggregator):
13. test_arbt04_signals_pass_under_limit      — signal accepted when below daily drawdown limit
14. test_arbt04_gate_triggers_at_limit        — gate triggers once cumulative exposure >= limit
15. test_arbt04_no_further_signals_after_gate — subsequent record_signal() calls return False after gate
16. test_arbt04_cumulative_exposure_tracks    — cumulative_exposure_usd reflects only accepted signals
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

try:
    from sportsbet.arbitrage.correlation_guard import CONFLICT_PAIRS, CorrelationGuard
    _GUARD_IMPORTED = True
except ImportError:
    CorrelationGuard = None  # type: ignore[assignment]
    CONFLICT_PAIRS = None  # type: ignore[assignment]
    _GUARD_IMPORTED = False

try:
    from sportsbet.arbitrage.aggregator import Aggregator
    _AGGREGATOR_IMPORTED = True
except ImportError:
    Aggregator = None  # type: ignore[assignment]
    _AGGREGATOR_IMPORTED = False


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


# ---------------------------------------------------------------------------
# Shared signal factory (Plan 02 — ARBT-03 and ARBT-04)
# ---------------------------------------------------------------------------

def _make_signal(market_type: str):
    """Build a minimal valid EVSignal for use in ARBT-03 and ARBT-04 tests."""
    from sportsbet.graph.models import EVSignal
    return EVSignal(
        ev_percentage=Decimal("0.05"),
        true_probability=Decimal("0.60"),
        implied_probability=Decimal("0.55"),
        kelly_fraction=Decimal("0.05"),
        trade_plan=["bullet 1", "bullet 2", "bullet 3"],
        market_type=market_type,
    )


# ---------------------------------------------------------------------------
# Test 9: CorrelationGuard blocks both signals in a conflict pair (ARBT-03)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _GUARD_IMPORTED, reason="sportsbet.arbitrage.correlation_guard not yet implemented")
def test_arbt03_conflict_blocked():
    """CorrelationGuard blocks both signals when their market_types form a CONFLICT_PAIR."""
    guard = CorrelationGuard()
    signal_over_passing = _make_signal("over_passing_yards")
    signal_under_total = _make_signal("under_total_points")
    result = guard.check([signal_over_passing, signal_under_total])
    assert result == [], (
        f"Expected [] (both blocked), got {[s.market_type for s in result]}"
    )


# ---------------------------------------------------------------------------
# Test 10: CorrelationGuard passes non-conflicting signal unchanged (ARBT-03)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _GUARD_IMPORTED, reason="sportsbet.arbitrage.correlation_guard not yet implemented")
def test_arbt03_no_conflict_passes():
    """A single non-conflicting signal passes through CorrelationGuard unchanged."""
    guard = CorrelationGuard()
    signal_moneyline = _make_signal("moneyline")
    result = guard.check([signal_moneyline])
    assert len(result) == 1, f"Expected 1 signal, got {len(result)}"
    assert result[0].market_type == "moneyline"


# ---------------------------------------------------------------------------
# Test 11: CONFLICT_PAIRS contains required pair (ARBT-03)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _GUARD_IMPORTED, reason="sportsbet.arbitrage.correlation_guard not yet implemented")
def test_arbt03_conflict_pairs_defined():
    """CONFLICT_PAIRS is a frozenset and contains over_passing_yards/under_total_points."""
    assert isinstance(CONFLICT_PAIRS, frozenset), (
        f"CONFLICT_PAIRS must be frozenset, got {type(CONFLICT_PAIRS)}"
    )
    required_pair = frozenset({"over_passing_yards", "under_total_points"})
    assert required_pair in CONFLICT_PAIRS, (
        f"CONFLICT_PAIRS must include {required_pair}, got {CONFLICT_PAIRS}"
    )


# ---------------------------------------------------------------------------
# Test 12: CorrelationGuard blocks only the conflicting pair (ARBT-03)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _GUARD_IMPORTED, reason="sportsbet.arbitrage.correlation_guard not yet implemented")
def test_arbt03_partial_conflict():
    """Only the conflicting pair is blocked; unrelated signals pass through."""
    guard = CorrelationGuard()
    signal_moneyline = _make_signal("moneyline")
    signal_over_passing = _make_signal("over_passing_yards")
    signal_under_total = _make_signal("under_total_points")
    result = guard.check([signal_moneyline, signal_over_passing, signal_under_total])
    assert len(result) == 1, (
        f"Expected 1 signal (moneyline only), got {[s.market_type for s in result]}"
    )
    assert result[0].market_type == "moneyline"


# ---------------------------------------------------------------------------
# Test 13: Aggregator accepts signal under daily drawdown limit (ARBT-04)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _AGGREGATOR_IMPORTED, reason="sportsbet.arbitrage.aggregator not yet implemented")
def test_arbt04_signals_pass_under_limit():
    """record_signal() returns True when cumulative exposure is below the daily limit."""
    agg = Aggregator(bankroll_usd=10000.0, daily_drawdown_limit=0.05)
    # kelly_fraction=0.02 → $200 exposure; limit = 0.05 * 10000 = $500
    signal = _make_signal("moneyline")
    # Override kelly_fraction to 0.02 for precise limit test
    from sportsbet.graph.models import EVSignal
    signal = EVSignal(
        ev_percentage=Decimal("0.05"),
        true_probability=Decimal("0.60"),
        implied_probability=Decimal("0.55"),
        kelly_fraction=Decimal("0.02"),
        trade_plan=["bullet 1", "bullet 2", "bullet 3"],
        market_type="moneyline",
    )
    result = agg.record_signal(signal)
    assert result is True, f"Expected True (signal under limit), got {result}"


# ---------------------------------------------------------------------------
# Test 14: Aggregator gate triggers when cumulative exposure reaches limit (ARBT-04)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _AGGREGATOR_IMPORTED, reason="sportsbet.arbitrage.aggregator not yet implemented")
def test_arbt04_gate_triggers_at_limit():
    """Gate triggers once cumulative exposure >= daily_drawdown_limit * bankroll."""
    from sportsbet.graph.models import EVSignal
    # bankroll=10000, limit=0.05 -> $500 max
    # Signal 1: kelly=0.03 -> $300 (accepted, cumulative=$300)
    # Signal 2: kelly=0.03 -> $300 (cumulative would be $600 >= $500 -> rejected)
    agg = Aggregator(bankroll_usd=10000.0, daily_drawdown_limit=0.05)
    signal_a = EVSignal(
        ev_percentage=Decimal("0.05"),
        true_probability=Decimal("0.60"),
        implied_probability=Decimal("0.55"),
        kelly_fraction=Decimal("0.03"),
        trade_plan=["bullet 1", "bullet 2", "bullet 3"],
        market_type="moneyline",
    )
    signal_b = EVSignal(
        ev_percentage=Decimal("0.05"),
        true_probability=Decimal("0.60"),
        implied_probability=Decimal("0.55"),
        kelly_fraction=Decimal("0.03"),
        trade_plan=["bullet 1", "bullet 2", "bullet 3"],
        market_type="spread",
    )
    result_a = agg.record_signal(signal_a)
    result_b = agg.record_signal(signal_b)
    assert result_a is True, f"Expected first signal accepted, got {result_a}"
    assert result_b is False, f"Expected second signal rejected (gate triggered), got {result_b}"


# ---------------------------------------------------------------------------
# Test 15: Aggregator gate stays closed after triggering (ARBT-04)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _AGGREGATOR_IMPORTED, reason="sportsbet.arbitrage.aggregator not yet implemented")
def test_arbt04_no_further_signals_after_gate():
    """Once gate is triggered, all subsequent record_signal() calls return False."""
    from sportsbet.graph.models import EVSignal
    # Trigger gate immediately: single large signal >= limit
    agg = Aggregator(bankroll_usd=10000.0, daily_drawdown_limit=0.05)
    large_signal = EVSignal(
        ev_percentage=Decimal("0.05"),
        true_probability=Decimal("0.60"),
        implied_probability=Decimal("0.55"),
        kelly_fraction=Decimal("0.25"),  # $2500 >> $500 limit
        trade_plan=["bullet 1", "bullet 2", "bullet 3"],
        market_type="total",
    )
    small_signal = EVSignal(
        ev_percentage=Decimal("0.05"),
        true_probability=Decimal("0.60"),
        implied_probability=Decimal("0.55"),
        kelly_fraction=Decimal("0.01"),
        trade_plan=["bullet 1", "bullet 2", "bullet 3"],
        market_type="moneyline",
    )
    # Large signal triggers gate
    first = agg.record_signal(large_signal)
    assert first is False, f"Expected large signal to trigger gate (False), got {first}"
    # All subsequent signals also rejected
    second = agg.record_signal(small_signal)
    third = agg.record_signal(small_signal)
    assert second is False, f"Expected second signal rejected after gate, got {second}"
    assert third is False, f"Expected third signal rejected after gate, got {third}"


# ---------------------------------------------------------------------------
# Test 16: Aggregator.cumulative_exposure_usd tracks accepted signals only (ARBT-04)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _AGGREGATOR_IMPORTED, reason="sportsbet.arbitrage.aggregator not yet implemented")
def test_arbt04_cumulative_exposure_tracks():
    """cumulative_exposure_usd increases by kelly_fraction * bankroll for each accepted signal."""
    from sportsbet.graph.models import EVSignal
    # bankroll=10000, limit=0.05 ($500)
    # Signal A: kelly=0.02 -> $200 accepted
    # Signal B: kelly=0.02 -> $200 accepted; cumulative=$400
    # Signal C: kelly=0.02 -> $200 would be $600 >= $500 -> rejected; cumulative stays $400
    agg = Aggregator(bankroll_usd=10000.0, daily_drawdown_limit=0.05)

    def _sig(kelly: str) -> EVSignal:
        return EVSignal(
            ev_percentage=Decimal("0.05"),
            true_probability=Decimal("0.60"),
            implied_probability=Decimal("0.55"),
            kelly_fraction=Decimal(kelly),
            trade_plan=["bullet 1", "bullet 2", "bullet 3"],
            market_type="moneyline",
        )

    assert agg.cumulative_exposure_usd == Decimal("0")
    agg.record_signal(_sig("0.02"))
    assert agg.cumulative_exposure_usd == Decimal("200"), (
        f"Expected $200 after first signal, got {agg.cumulative_exposure_usd}"
    )
    agg.record_signal(_sig("0.02"))
    assert agg.cumulative_exposure_usd == Decimal("400"), (
        f"Expected $400 after second signal, got {agg.cumulative_exposure_usd}"
    )
    # Third signal rejected — cumulative must NOT change
    rejected = agg.record_signal(_sig("0.02"))
    assert rejected is False
    assert agg.cumulative_exposure_usd == Decimal("400"), (
        f"Cumulative must not change after rejected signal, got {agg.cumulative_exposure_usd}"
    )
