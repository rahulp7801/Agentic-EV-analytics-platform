"""Unit tests for BacktestEngine (QUANT-04).

All tests use fixture data only — no DB, no asyncpg, no graph dependency.

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

import logging
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from sportsbet.graph.models import QuantResult
from sportsbet.quant.backtest import BacktestEngine, BacktestReport, BacktestSignal

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

_GAME_START = datetime(2024, 1, 14, 18, 0, 0, tzinfo=timezone.utc)
_SNAPSHOT = datetime(2024, 1, 14, 12, 0, 0, tzinfo=timezone.utc)  # < game_start


def make_signals(n_wins: int, n_losses: int) -> list[BacktestSignal]:
    """Build a list of BacktestSignal instances for fixture data.

    Uses payout_multiplier=1.909 (approx -110 American odds) and stake=100.
    signal implied prob = 0.55, closing implied prob = 0.60.
    """
    signals: list[BacktestSignal] = []
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
                entry_time=_SNAPSHOT.replace(hour=10),
                entry_implied_prob=Decimal("0.55"),
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
                entry_time=_SNAPSHOT.replace(hour=10),
                entry_implied_prob=Decimal("0.55"),
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_backtest_engine_fixture() -> None:
    """BacktestEngine().run(5_signals_3_wins) returns BacktestReport with
    hit_rate == 0.6, roi close to 0.1454, sample_size == 5."""
    signals = make_signals(n_wins=3, n_losses=2)
    report = BacktestEngine().run(signals)

    assert report.sample_size == 5
    assert report.hit_rate == pytest.approx(0.6, abs=1e-6)
    assert report.roi == pytest.approx(0.1454, abs=1e-3)


def test_backtest_empty_signals() -> None:
    """BacktestEngine().run([]) returns BacktestReport with sample_size=0,
    roi=None, hit_rate=None, clv_mean=None — no ZeroDivisionError."""
    report = BacktestEngine().run([])

    assert report.sample_size == 0
    assert report.roi is None
    assert report.hit_rate is None
    assert report.clv_mean is None
    assert report.signals_df is None


def test_backtest_clv_positive_when_signal_beats_close() -> None:
    """signal_implied_prob=0.55, closing_implied_prob=0.60 → clv_mean > 0.

    CLV = closing_implied_prob - signal_implied_prob = 0.60 - 0.55 = 0.05.
    Positive CLV means the signal was priced more favorably than the close.
    """
    signals = make_signals(n_wins=1, n_losses=0)
    report = BacktestEngine().run(signals)

    assert report.clv_mean is not None
    assert report.clv_mean > 0
    assert report.clv_mean == pytest.approx(0.05, abs=1e-6)


def test_backtest_report_has_signals_df() -> None:
    """BacktestEngine().run(non_empty) returns report with signals_df as a
    pandas DataFrame with len == 5."""
    signals = make_signals(n_wins=3, n_losses=2)
    report = BacktestEngine().run(signals)

    assert report.signals_df is not None
    assert isinstance(report.signals_df, pd.DataFrame)
    assert len(report.signals_df) == 5


def test_backtest_roi_calculation() -> None:
    """Exact ROI spot-check: 3 wins at payout 1.909, stake 100; 2 losses at stake 100.

    roi = 72.7 / 500 = 0.1454 (within 1e-3 tolerance).
    """
    signals = make_signals(n_wins=3, n_losses=2)
    report = BacktestEngine().run(signals)

    # Manual: 3 * (100 * 0.909) - 2 * 100 = 272.7 - 200 = 72.7; 72.7/500 = 0.1454
    assert report.roi is not None
    assert report.roi == pytest.approx(0.1454, abs=1e-3)


def test_backtest_cli_requires_real_input(monkeypatch, capsys) -> None:
    from sportsbet.quant.backtest import main
    monkeypatch.setattr("sys.argv", ["backtest"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert "required" in output.err


def test_backtest_skips_null_probability_signal(caplog: pytest.LogCaptureFixture) -> None:
    """BacktestEngine().run() with a signal where quant_result.true_probability
    is None — that signal is excluded from DataFrame computation; a warning is
    emitted; sample_size reflects only valid signals."""
    null_signal = BacktestSignal(
        quant_result=QuantResult(true_probability=None),
        closing_implied_prob=Decimal("0.60"),
        actual_outcome=True,
        stake=Decimal("100"),
        payout_multiplier=Decimal("1.909"),
        game_start_time=_GAME_START,
        snapshot_time=_SNAPSHOT,
                entry_time=_SNAPSHOT.replace(hour=10),
                entry_implied_prob=Decimal("0.55"),
    )
    valid_signals = make_signals(n_wins=2, n_losses=1)
    all_signals = [null_signal] + valid_signals

    with caplog.at_level(logging.WARNING):
        report = BacktestEngine().run(all_signals)

    # Null signal excluded — only 3 valid signals processed
    assert report.sample_size == 4
    assert report.calibration_count == 3
    assert report.signals_df is not None
    assert len(report.signals_df) == 4
