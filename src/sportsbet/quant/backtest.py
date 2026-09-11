"""Offline evaluation with separate model, entry-price and closing-price metrics."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal
import pandas as pd
from sportsbet.graph.models import QuantResult

Outcome = bool | Literal["push", "void"] | None

@dataclass
class BacktestSignal:
    quant_result: QuantResult
    closing_implied_prob: Decimal | None
    actual_outcome: Outcome
    stake: Decimal
    payout_multiplier: Decimal  # gross decimal payout at entry
    game_start_time: datetime
    snapshot_time: datetime  # closing quote time
    entry_time: datetime | None = None
    entry_implied_prob: Decimal | None = None
    push_probability: Decimal = Decimal("0")

@dataclass
class BacktestReport:
    roi: float | None = None
    hit_rate: float | None = None
    clv_mean: float | None = None
    sample_size: int = 0
    signals_df: pd.DataFrame | None = None
    settled_count: int = 0
    decided_count: int = 0
    pending_count: int = 0
    void_count: int = 0
    clv_count: int = 0
    calibration_count: int = 0
    brier_score: float | None = None
    log_loss: float | None = None
    calibration: list[dict] = field(default_factory=list)
    closing_line_note: str = "CLV is same-line raw implied-probability movement; requires entry < close < start."

def _probability(value: Decimal | None) -> float | None:
    if value is None:
        return None
    if not value.is_finite() or not 0 <= value <= 1:
        raise ValueError("Probability must be finite and within [0, 1]")
    return float(value)


def calibration_metrics(predictions: list[tuple[float, int]]) -> dict:
    """Probability scoring shared by priced replay and unpriced forecast checks."""
    if any(not math.isfinite(p) or not 0 <= p <= 1 or y not in (0, 1) for p, y in predictions):
        raise ValueError('Calibration needs finite probabilities and binary outcomes')
    result = dict(calibration_count=len(predictions), brier_score=None, log_loss=None, calibration=[])
    if not predictions:
        return result
    result['brier_score'] = sum((p-y)**2 for p, y in predictions) / len(predictions)
    result['log_loss'] = -sum(y*math.log(max(1e-15,p)) + (1-y)*math.log(max(1e-15,1-p)) for p,y in predictions) / len(predictions)
    for bucket in range(10):
        group = [(p,y) for p,y in predictions if min(int(p*10),9) == bucket]
        if group:
            result['calibration'].append(dict(lower=bucket/10, upper=(bucket+1)/10,
                count=len(group), predicted=sum(p for p,_ in group)/len(group),
                observed=sum(y for _,y in group)/len(group)))
    return result

class BacktestEngine:
    def run(self, signals: list[BacktestSignal]) -> BacktestReport:
        report = BacktestReport(sample_size=len(signals))
        rows = []
        predictions: list[tuple[float, int]] = []
        profits, stakes, clvs, wins = [], [], [], []
        for s in signals:
            outcome = s.actual_outcome
            if outcome is not None and type(outcome) is not bool and outcome not in ("push", "void"):
                raise ValueError("Outcome must be true, false, push, void, or null")
            if not s.stake.is_finite() or s.stake < 0 or not s.payout_multiplier.is_finite() or s.payout_multiplier <= 1:
                raise ValueError("Stake must be nonnegative and gross payout greater than one")
            timestamps = [s.game_start_time, s.snapshot_time] + ([s.entry_time] if s.entry_time else [])
            if any(t.tzinfo is None or t.utcoffset() is None for t in timestamps):
                raise ValueError("Evaluation timestamps must include a timezone")
            if s.entry_time is not None and s.entry_time >= s.game_start_time:
                raise ValueError("Prediction/entry must precede game start")
            p = _probability(s.quant_result.true_probability)
            push = _probability(s.push_probability)
            if p is not None and p + push > 1.00000001:
                raise ValueError("Win and push probability exceed one")
            entry = _probability(s.entry_implied_prob if s.entry_implied_prob is not None else 1 / s.payout_multiplier)
            close = _probability(s.closing_implied_prob)
            clv = None
            if close is not None and s.entry_time is not None and s.entry_time < s.snapshot_time < s.game_start_time:
                clv = close - entry
                clvs.append(clv)
            profit = None
            if outcome is None:
                report.pending_count += 1
            elif outcome == "void":
                report.void_count += 1
            else:
                report.settled_count += 1
                profit = float(s.stake * (s.payout_multiplier - 1)) if outcome is True else (-float(s.stake) if outcome is False else 0.0)
                profits.append(profit)
                stakes.append(float(s.stake))
                if type(outcome) is bool:
                    wins.append(int(outcome))
                    if p is not None and push < 1:
                        predictions.append((p / (1 - push), int(outcome)))
            rows.append(dict(model_probability=p, signal_implied_prob=entry, closing_implied_prob=close,
                actual_outcome=outcome, profit=profit, stake=float(s.stake), raw_clv=clv,
                payout_multiplier=float(s.payout_multiplier), game_start_time=s.game_start_time,
                snapshot_time=s.snapshot_time, entry_time=s.entry_time))
        report.signals_df = pd.DataFrame(rows) if rows else None
        report.decided_count = len(wins)
        report.clv_count = len(clvs)
        report.calibration_count = len(predictions)
        report.roi = sum(profits) / sum(stakes) if sum(stakes) > 0 else None
        report.hit_rate = sum(wins) / len(wins) if wins else None
        report.clv_mean = sum(clvs) / len(clvs) if clvs else None
        for name, value in calibration_metrics(predictions).items():
            setattr(report, name, value)
        return report

def main() -> None:
    from sportsbet.quant.backtest_replay import main as replay
    replay()

if __name__ == "__main__":
    main()
