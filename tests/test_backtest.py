"""Unit tests for BacktestEngine (QUANT-04).

All tests use fixture data only — no DB, no asyncpg, no graph dependency.
Imports are wrapped in try/except ImportError to produce clean RED failures
before the module is implemented.

Fixture ROI spot-check (from plan verification):
  3 wins at payout_multiplier=1.909 on stake=100:
    profit per win = 100 * (1.909 - 1) = 90.9
    total win profit = 3 * 90.9 = 272.7
  2 losses at stake=100:
    total loss = 2 * 100 = 200
  net profit = 272.7 - 200 = 72.7
  total staked = 5 * 100 = 500
  roi = 72.7 / 500 = 0.1454
"""
from __future__ import annotations

import warnings
from datetime import datetime, timezone
from decimal import Decimal

import pytest

try:
    from sportsbet.quant.backtest import BacktestEngine, BacktestReport, BacktestSignal

    IMPORT_OK = True
except ImportError:
    IMPORT_OK = False

from sportsbet.graph.models import QuantResult

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

_GAME_START = datetime(2024, 1, 14, 18, 0, 0, tzinfo=timezone.utc)
_SNAPSHOT = datetime(2024, 1, 14, 12, 0, 0, tzinfo=timezone.utc)  # < game_start


def make_signals(n_wins: int, n_losses: int) -> list:  # type: ignore[type-arg]
    """Build a list of BacktestSignal instances for fixture data.

    Uses payout_multiplier=1.909 (approx -110 American odds) and stake=100.
    signal implied prob = 0.55, closing implied prob = 0.60.
    """
    if not IMPORT_OK:
        return []

    signals = []
    for _ in range(n_wins):
        signals.append(
            BacktestSignal(
                quant_result=QuantResult(true_probability=Decimal("0.55")),
                closing_implied_prob=Decimal("0.60"),
                actual_outcome=True,
                stake=Decimal("100"),
                payout_multiplier=Decimal("1.909"),
                game_start_time=_GAME_START,
                snapshot_time=_SNAPSHOT,
            )
        )
    for _ in range(n_losses):
        signals.append(
            BacktestSignal(
                quant_result=QuantResult(true_probability=Decimal("0.55")),
                closing_implied_prob=Decimal("0.60"),
                actual_outcome=False,
                stake=Decimal("100"),
                payout_multiplier=Decimal("1.909"),
                game_start_time=_GAME_START,
                snapshot_time=_SNAPSHOT,
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_backtest_engine_fixture() -> None:
    """BacktestEngine().run(5_signals_3_wins) returns BacktestReport with
    hit_rate == 0.6, roi close to 0.1454, sample_size == 5."""
    raise AssertionError("not implemented")


def test_backtest_empty_signals() -> None:
    """BacktestEngine().run([]) returns BacktestReport with sample_size=0,
    roi=None, hit_rate=None, clv_mean=None — no ZeroDivisionError."""
    raise AssertionError("not implemented")


def test_backtest_clv_positive_when_signal_beats_close() -> None:
    """signal_implied_prob=0.55, closing_implied_prob=0.60 → raw_clv > 0.

    CLV = closing_implied_prob - signal_implied_prob = 0.60 - 0.55 = 0.05.
    Positive CLV means the signal was priced more favorably than the close.
    """
    raise AssertionError("not implemented")


def test_backtest_report_has_signals_df() -> None:
    """BacktestEngine().run(non_empty) returns report with signals_df as a
    pandas DataFrame with len == 5."""
    raise AssertionError("not implemented")


def test_backtest_roi_calculation() -> None:
    """Exact ROI spot-check: 3 wins at payout 1.909, stake 100; 2 losses at stake 100.

    roi = 72.7 / 500 = 0.1454 (4 decimal places, within 1e-3 tolerance).
    """
    raise AssertionError("not implemented")


def test_backtest_skips_null_probability_signal() -> None:
    """BacktestEngine().run() with a signal where quant_result.true_probability
    is None — that signal is excluded from DataFrame computation; a warning is
    emitted; sample_size reflects only valid signals."""
    raise AssertionError("not implemented")
