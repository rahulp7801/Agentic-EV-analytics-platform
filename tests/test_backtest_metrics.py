from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import pytest
from sportsbet.graph.models import QuantResult
from sportsbet.quant.backtest import BacktestSignal, BacktestEngine
from sportsbet.quant.backtest_replay import build_signals

START = datetime(2026, 1, 10, 18, tzinfo=timezone.utc)

def signal(**kw):
    return replace(BacktestSignal(QuantResult(true_probability=Decimal('0.6')), Decimal('0.55'),
        True, Decimal('1'), Decimal('2'), START, START-timedelta(minutes=1),
        START-timedelta(hours=2)), **kw)

def test_metrics_separate_price_model_and_outcome():
    report = BacktestEngine().run([signal(), signal(actual_outcome=False)])
    assert report.clv_mean == pytest.approx(0.05)
    assert report.brier_score == pytest.approx(0.26)
    assert report.log_loss == pytest.approx(-math.log(0.6 * 0.4) / 2)
    assert report.roi == 0
    assert report.calibration == [dict(lower=0.6, upper=0.7, count=2, predicted=0.6, observed=0.5)]
    changed = BacktestEngine().run([signal(quant_result=QuantResult(true_probability=Decimal('0.9')))])
    assert changed.clv_mean == pytest.approx(report.clv_mean)

def test_pending_push_and_void_are_not_losses():
    report = BacktestEngine().run([signal(), signal(actual_outcome='push'),
        signal(actual_outcome=None), signal(actual_outcome='void')])
    assert report.roi == 0.5
    assert report.hit_rate == 1
    assert (report.settled_count, report.pending_count, report.void_count, report.calibration_count) == (2,1,1,1)
    assert BacktestEngine().run([signal(actual_outcome=None)]).roi is None

def test_zero_stake_and_missing_model_do_not_invent_metrics():
    report = BacktestEngine().run([signal(stake=Decimal(0), quant_result=QuantResult())])
    assert report.roi is None and report.brier_score is None
    assert report.clv_mean == pytest.approx(0.05)

@pytest.mark.parametrize('close', [START, START+timedelta(minutes=1), START-timedelta(hours=2)])
def test_inplay_or_same_quote_has_no_clv(close):
    report = BacktestEngine().run([signal(snapshot_time=close)])
    assert report.clv_mean is None and report.clv_count == 0

def test_invalid_probabilities_and_time_are_rejected():
    with pytest.raises(ValueError):
        BacktestEngine().run([signal(quant_result=QuantResult(true_probability=Decimal('NaN')))])
    with pytest.raises(ValueError):
        BacktestEngine().run([signal(entry_time=START)])

def quote(id, price, hour, **kw):
    return dict(id=id, game_id='game', sportsbook='book', market_type='points', outcome_name='Over',
        player_name='Player', line=20.5, price=price, game_start_time=START,
        snapped_at=START-timedelta(hours=hour)) | kw

def test_replay_matches_identity_and_distinct_quotes():
    rows = [quote(1, 100, 2), quote(2,-120,1), quote(3,-500,-1),
        quote(4,-200,1,outcome_name='Under'), quote(5,-300,1,line=21.5)]
    signals = build_signals(rows, {'1':True})
    assert len(signals) == 3
    report = BacktestEngine().run(signals)
    assert report.clv_mean == pytest.approx(120/220 - 0.5)
    assert report.clv_count == 1
    assert report.pending_count == 2
    assert report.roi == 1
    assert report.brier_score is None

def test_legacy_missing_identity_does_not_fabricate_clv():
    assert build_signals([quote(1,100,2,outcome_name=None)]) == []
