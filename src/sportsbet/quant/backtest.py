"""Backtesting replay module for QUANT-04.

BacktestEngine is a standalone offline module. It is never imported from within
the LangGraph graph (graph.py) or any agent node. Run separately as a CLI or
test fixture.

Design contract:
- Accepts a list of BacktestSignal records (historical QuantResult signals
  paired with actual outcomes and closing lines).
- Returns a BacktestReport with ROI, hit-rate, and CLV metrics computed via
  vectorized pandas operations.
- Degrades gracefully on empty input or all-null-probability input.

Closing line note (Pitfall 6 from RESEARCH.md):
    snapshot_time < game_start_time is the **caller's responsibility**.
    BacktestEngine does not have DB access and cannot enforce this constraint.
    Callers must use odds_snapshots WHERE snapped_at < game_start_time when
    constructing BacktestSignal.closing_implied_prob to avoid in-play price
    contamination.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

import pandas as pd
import structlog

from sportsbet.graph.models import QuantResult

logger = structlog.get_logger(__name__)


@dataclass
class BacktestSignal:
    """One historical signal record for backtesting replay.

    Fields:
        quant_result: The Quant Agent's probability estimate at signal time.
        closing_implied_prob: Fair closing-line probability (post-devig via
            vig.py). Caller must ensure this was snapped before game_start_time.
        actual_outcome: True = bet won, False = bet lost.
        stake: Notional stake for this signal (e.g. Decimal("100")).
        payout_multiplier: Decimal odds payout (e.g. Decimal("1.909") for -110).
        game_start_time: Kick-off / tip-off time. Used only for documentation;
            BacktestEngine does not enforce the snapshot_time < game_start_time
            constraint — callers are responsible for this guard.
        snapshot_time: Time when closing_implied_prob was observed. Must be <
            game_start_time per closing-line convention (caller enforces).
    """

    quant_result: QuantResult
    closing_implied_prob: Decimal
    actual_outcome: bool
    stake: Decimal
    payout_multiplier: Decimal
    game_start_time: datetime
    snapshot_time: datetime


@dataclass
class BacktestReport:
    """Aggregated metrics from a backtesting run.

    Fields:
        roi: sum(profit) / sum(stake); None if sample_size == 0.
        hit_rate: wins / total_bets; None if sample_size == 0.
        clv_mean: mean(closing_implied_prob - signal_implied_prob); None if
            sample_size == 0. Positive CLV = signal was priced more favorably
            than the closing line (good leading indicator of edge).
        sample_size: Number of valid signals processed (excludes signals where
            quant_result.true_probability is None).
        signals_df: Enriched DataFrame with one row per valid signal and columns
            [signal_implied_prob, closing_implied_prob, raw_clv, profit, stake,
            actual_outcome, payout_multiplier]; None if sample_size == 0.
        closing_line_note: Documents the pre-game snapshot constraint.
    """

    roi: Optional[float]
    hit_rate: Optional[float]
    clv_mean: Optional[float]
    sample_size: int
    signals_df: Optional[pd.DataFrame]
    closing_line_note: str = field(
        default="snapshot_time < game_start_time is caller's responsibility"
    )


class BacktestEngine:
    """Offline backtesting engine for QuantResult signals.

    Replay historical signals against actual outcomes and closing lines.
    Computes ROI, hit-rate, and CLV using vectorized pandas operations.

    Usage:
        engine = BacktestEngine()
        report = engine.run(signals)

    Isolation guarantee:
        BacktestEngine is never imported from within the LangGraph graph
        (graph.py) or any agent node. It is a standalone offline module.
    """

    def run(self, signals: list[BacktestSignal]) -> BacktestReport:
        """Run backtesting replay on a list of historical signals.

        Args:
            signals: List of BacktestSignal records. Empty list returns a
                BacktestReport with sample_size=0 and all None metrics.

        Returns:
            BacktestReport with ROI, hit_rate, clv_mean, sample_size,
            and an enriched signals_df DataFrame.

        Notes:
            Signals where quant_result.true_probability is None are skipped.
            A structlog warning is emitted for each skipped signal.
            If all signals are skipped, returns sample_size=0 with all None.

            snapshot_time < game_start_time is the caller's responsibility —
            this method does not validate timestamps.
        """
        if not signals:
            return BacktestReport(
                roi=None,
                hit_rate=None,
                clv_mean=None,
                sample_size=0,
                signals_df=None,
            )

        # Filter out signals with null true_probability
        valid_signals: list[BacktestSignal] = []
        for s in signals:
            if s.quant_result.true_probability is None:
                logger.warning(
                    "skipping_null_probability_signal",
                    game_start_time=str(s.game_start_time),
                )
            else:
                valid_signals.append(s)

        if not valid_signals:
            return BacktestReport(
                roi=None,
                hit_rate=None,
                clv_mean=None,
                sample_size=0,
                signals_df=None,
            )

        # Build DataFrame from valid signals
        rows = []
        for s in valid_signals:
            rows.append(
                {
                    "signal_implied_prob": float(s.quant_result.true_probability),
                    "closing_implied_prob": float(s.closing_implied_prob),
                    "actual_outcome": s.actual_outcome,
                    "stake": float(s.stake),
                    "payout_multiplier": float(s.payout_multiplier),
                    "game_start_time": s.game_start_time,
                    "snapshot_time": s.snapshot_time,
                }
            )

        df = pd.DataFrame(rows)

        # CLV: positive = signal was priced more favorably than close
        df["raw_clv"] = df["closing_implied_prob"] - df["signal_implied_prob"]

        # Profit: win = stake * (payout_multiplier - 1), loss = -stake
        df["profit"] = df.apply(
            lambda r: r["stake"] * (r["payout_multiplier"] - 1)
            if r["actual_outcome"]
            else -r["stake"],
            axis=1,
        )

        roi = float(df["profit"].sum() / df["stake"].sum())
        hit_rate = float(df["actual_outcome"].mean())
        clv_mean = float(df["raw_clv"].mean())

        return BacktestReport(
            roi=roi,
            hit_rate=hit_rate,
            clv_mean=clv_mean,
            sample_size=len(df),
            signals_df=df,
        )


# ---------------------------------------------------------------------------
# CLI entry point — python -m sportsbet.quant.backtest
# ---------------------------------------------------------------------------

def main() -> None:
    """Run BacktestEngine against a fixture dataset and print ROI, hit-rate, CLV.

    Fixture: 3 wins + 2 losses at -110 (-0.1 payout ratio per loss, +0.909 per win).
    Use as a smoke test that BacktestEngine is importable and functional.
    """
    from datetime import datetime, timezone

    _GAME_START = datetime(2024, 1, 14, 18, 0, 0, tzinfo=timezone.utc)
    _SNAPSHOT = datetime(2024, 1, 14, 12, 0, 0, tzinfo=timezone.utc)

    fixture_signals: list[BacktestSignal] = [
        BacktestSignal(
            quant_result=QuantResult(true_probability=Decimal("0.55")),
            closing_implied_prob=Decimal("0.60"),
            actual_outcome=won,
            stake=Decimal("100"),
            payout_multiplier=Decimal("1.909"),
            game_start_time=_GAME_START,
            snapshot_time=_SNAPSHOT,
        )
        for won in [True, True, True, False, False]
    ]

    report = BacktestEngine().run(fixture_signals)
    print(f"sample_size : {report.sample_size}")
    if report.roi is not None:
        print(f"hit_rate    : {report.hit_rate:.4f}")
        print(f"roi         : {report.roi:.4f}")
        print(f"clv_mean    : {report.clv_mean:.4f}")
    else:
        print("No valid signals to report.")


if __name__ == "__main__":
    import sys
    main()
    sys.exit(0)
