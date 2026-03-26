"""Tests for QUANT-04 backtest_replay.py CLI pipeline.

SC-6: odds_snapshots -> BacktestSignal -> BacktestReport pipeline.
Tests cover CLV-only mode, full ROI mode, and empty snapshots.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsbet.quant.backtest_replay import build_signals, load_snapshots  # noqa: F401

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_ROW = {
    "id": 1,
    "game_id": "2024_01_KC_DET",
    "sportsbook": "fanduel",
    "market_type": "h2h",
    "line": None,
    "price": -110,
    "snapped_at": datetime(2024, 1, 14, 12, 0, 0, tzinfo=timezone.utc),
    "game_start_time": datetime(2024, 1, 14, 18, 0, 0, tzinfo=timezone.utc),
}

FIXTURE_ROW_POSITIVE_ODDS = {
    "id": 2,
    "game_id": "2024_01_KC_DET",
    "sportsbook": "draftkings",
    "market_type": "h2h",
    "line": None,
    "price": 120,
    "snapped_at": datetime(2024, 1, 14, 12, 30, 0, tzinfo=timezone.utc),
    "game_start_time": datetime(2024, 1, 14, 18, 0, 0, tzinfo=timezone.utc),
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_clv_only_mode() -> None:
    """CLV-only mode: build_signals with no outcomes sets actual_outcome=False.

    BacktestEngine.run() should produce a BacktestReport with clv_mean
    populated (not None) since we have valid signals with true_probability set.
    """
    from sportsbet.quant.backtest import BacktestEngine

    rows = [FIXTURE_ROW, FIXTURE_ROW_POSITIVE_ODDS]
    signals = build_signals(rows, outcomes=None)

    # All signals have actual_outcome=False in CLV-only mode
    assert len(signals) == 2
    for sig in signals:
        assert sig.actual_outcome is False

    # BacktestEngine produces a report with clv_mean populated
    report = BacktestEngine().run(signals)
    assert report.sample_size == 2
    assert report.clv_mean is not None, "clv_mean must be populated in CLV-only mode"


def test_full_roi_mode() -> None:
    """Full ROI mode: build_signals with outcomes dict sets actual_outcome from dict.

    hit_rate should be populated in the report when actual outcomes are provided.
    """
    from sportsbet.quant.backtest import BacktestEngine

    rows = [FIXTURE_ROW, FIXTURE_ROW_POSITIVE_ODDS]
    outcomes = {"2024_01_KC_DET": True}  # win for this game_id
    signals = build_signals(rows, outcomes=outcomes)

    # actual_outcome pulled from outcomes dict for matching game_id
    assert len(signals) == 2
    for sig in signals:
        assert sig.actual_outcome is True  # both rows share game_id "2024_01_KC_DET"

    # BacktestEngine produces a report with hit_rate populated
    report = BacktestEngine().run(signals)
    assert report.sample_size == 2
    assert report.hit_rate is not None, "hit_rate must be populated when outcomes provided"
    assert report.hit_rate == 1.0  # all won


def test_empty_snapshots() -> None:
    """Empty input: build_signals([]) returns [] and BacktestEngine produces sample_size=0."""
    from sportsbet.quant.backtest import BacktestEngine

    signals = build_signals([])
    assert signals == []

    report = BacktestEngine().run(signals)
    assert report.sample_size == 0
    assert report.clv_mean is None
