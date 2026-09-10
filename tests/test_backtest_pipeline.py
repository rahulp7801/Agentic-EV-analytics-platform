"""Quote replay contract: preserve missing data and selection-specific outcomes."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest
from sportsbet.quant.backtest_replay import build_signals, load_snapshots
from sportsbet.quant.backtest import BacktestEngine

START = datetime(2024,1,14,18,tzinfo=timezone.utc)
ROW = dict(id=1,game_id='game',sportsbook='book',market_type='h2h',outcome_name='KC',line=None,
           price=-110, snapped_at=START-timedelta(hours=2),game_start_time=START)

def test_clv_only_mode():
    signals = build_signals([ROW, ROW | dict(id=2,price=-120,snapped_at=START-timedelta(minutes=1))])
    report = BacktestEngine().run(signals)
    assert signals[0].actual_outcome is None
    assert report.roi is None and report.hit_rate is None and report.brier_score is None
    assert report.clv_mean > 0

def test_outcomes_are_keyed_by_selection_entry_id():
    signals = build_signals([ROW, ROW | dict(id=3,outcome_name='DET')], {'1':True,'3':False})
    assert [s.actual_outcome for s in signals] == [True, False]

def test_missing_outcomes_and_rows():
    assert build_signals([]) == []
    assert build_signals([ROW | dict(game_start_time=None)]) == []
    assert build_signals([ROW], {'game':True})[0].actual_outcome is None

async def test_loader_does_not_guess_start_time():
    conn = AsyncMock()
    conn.fetch.return_value = []
    await load_snapshots(conn, 'game', 'h2h')
    sql, *args = conn.fetch.call_args.args
    assert '18 hours' not in sql and 'snapped_at < game_start_time' in sql
    assert args == ['game','h2h']
