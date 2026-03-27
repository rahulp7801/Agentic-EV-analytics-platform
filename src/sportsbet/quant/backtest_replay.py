"""CLI entry point for QUANT-04 automated BacktestEngine pipeline from odds_snapshots.

Queries odds_snapshots rows from PostgreSQL, maps them to BacktestSignal inputs,
and runs BacktestEngine for automated closing-line value (CLV) analysis.

Default mode is CLV-only (no actual_outcome required).
An optional --outcomes-file JSON argument enables full ROI/hit-rate reporting.

Design contract:
- load_snapshots(): async query odds_snapshots JOIN games WHERE snapped_at < game_start_time
- build_signals(): maps snapshot dicts to BacktestSignal; actual_outcome=False in CLV-only mode
- main(): CLI entry point; prints clv_mean always; prints roi/hit_rate only when outcomes-file provided

Closing line note (Pitfall 6 from RESEARCH.md):
    The SQL WHERE clause enforces snapped_at < game_start_time to prevent
    in-play price contamination. This is the pipeline-level enforcement of the
    BacktestEngine caller contract.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import asyncpg
import structlog

from sportsbet.config import settings
from sportsbet.graph.models import QuantResult
from sportsbet.quant.backtest import BacktestEngine, BacktestSignal

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Odds conversion helpers (consistent with graph/agents.py _extract_odds_snapshot)
# ---------------------------------------------------------------------------


def _american_to_implied_prob(price: int) -> Decimal:
    """Convert American odds to implied probability (without vig).

    Positive: implied = 100 / (price + 100)
    Negative: implied = abs(price) / (abs(price) + 100)

    Returns Decimal rounded to 6 decimal places.
    """
    if price > 0:
        return Decimal(str(round(100 / (price + 100), 6)))
    else:
        return Decimal(str(round(abs(price) / (abs(price) + 100), 6)))


def _american_to_payout(price: int) -> Decimal:
    """Convert American odds to payout multiplier (consistent with graph/agents.py).

    Positive: payout = 1 + price / 100
    Negative: payout = 1 + 100 / abs(price)

    Returns Decimal rounded to 6 decimal places.
    """
    if price > 0:
        return Decimal(str(round(1 + price / 100, 6)))
    else:
        return Decimal(str(round(1 + 100 / abs(price), 6)))


# ---------------------------------------------------------------------------
# Signal builder
# ---------------------------------------------------------------------------


def build_signals(
    rows: list[dict],
    outcomes: dict[str, bool] | None = None,
) -> list[BacktestSignal]:
    """Map odds_snapshots dicts to BacktestSignal records.

    Args:
        rows: List of snapshot dicts. Each dict must contain keys matching the
            odds_snapshots columns plus ``game_start_time`` (JOIN-derived).
        outcomes: Optional dict mapping game_id -> bool actual outcome.
            When None (CLV-only mode), actual_outcome=False for all signals.

    Returns:
        List of BacktestSignal records. Rows where price is None are skipped.
    """
    signals: list[BacktestSignal] = []

    for row in rows:
        price = row.get("price")
        if price is None:
            logger.debug("skipping_row_no_price", row_id=row.get("id"))
            continue

        game_start_time = row.get("game_start_time")
        if game_start_time is None:
            logger.debug("skipping_row_no_game_start_time", row_id=row.get("id"), game_id=row.get("game_id"))
            continue

        game_id = row.get("game_id")
        closing_implied_prob = _american_to_implied_prob(price)
        payout_multiplier = _american_to_payout(price)
        actual_outcome: bool = outcomes.get(game_id, False) if outcomes else False
        snapshot_time: datetime = row["snapped_at"]

        # CLV-only: use closing prob as signal probability so clv_mean reflects
        # closing line movement from snapshot to game-time.
        quant_result = QuantResult(true_probability=closing_implied_prob)

        signals.append(
            BacktestSignal(
                quant_result=quant_result,
                closing_implied_prob=closing_implied_prob,
                actual_outcome=actual_outcome,
                stake=Decimal("100"),
                payout_multiplier=payout_multiplier,
                game_start_time=game_start_time,
                snapshot_time=snapshot_time,
            )
        )

    return signals


# ---------------------------------------------------------------------------
# Async DB loader
# ---------------------------------------------------------------------------


async def load_snapshots(
    conn: asyncpg.Connection,
    game_id: str | None = None,
    market_type: str | None = None,
) -> list[dict]:
    """Query odds_snapshots rows joined with games for game_start_time.

    SQL enforces snapped_at < game_start_time to prevent in-play contamination
    (Pitfall 6 caller contract — enforced at pipeline layer here).

    The 18:00 UTC default kickoff time is a v1 pragmatic default for NFL games
    (per RESEARCH.md open question 3).

    Args:
        conn: asyncpg Connection (not pool) for single-connection usage.
        game_id: Optional filter to specific game_id.
        market_type: Optional filter to specific market_type (e.g. "h2h").

    Returns:
        List of dicts with odds_snapshots columns plus game_start_time.
    """
    # Build query with optional filters using positional parameters
    params: list[str] = []
    where_clauses = [
        "o.game_id IS NOT NULL",                                            # QUANT-04: filter NULL game_id rows before LEFT JOIN timestamp arithmetic
        "o.snapped_at < (g.game_date::timestamptz + INTERVAL '18 hours')",
        "o.price IS NOT NULL",
    ]

    if game_id is not None:
        params.append(game_id)
        where_clauses.append(f"o.game_id = ${len(params)}")

    if market_type is not None:
        params.append(market_type)
        where_clauses.append(f"o.market_type = ${len(params)}")

    where_sql = " AND ".join(where_clauses)

    query = f"""
        SELECT
            o.id,
            o.game_id,
            o.sportsbook,
            o.market_type,
            o.line,
            o.price,
            o.snapped_at,
            (g.game_date::timestamptz + INTERVAL '18 hours') AS game_start_time
        FROM odds_snapshots o
        LEFT JOIN games g ON o.game_id = g.game_id
        WHERE {where_sql}
        ORDER BY o.snapped_at
    """

    rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _async_main(
    db_url: str,
    game_id: Optional[str],
    market: Optional[str],
    outcomes: Optional[dict[str, bool]],
    has_outcomes_file: bool,
) -> None:
    """Async body of main() for asyncio.run() compatibility."""
    conn: asyncpg.Connection = await asyncpg.connect(dsn=db_url)
    try:
        rows = await load_snapshots(conn, game_id=game_id, market_type=market)
    finally:
        await conn.close()

    signals = build_signals(rows, outcomes=outcomes)
    report = BacktestEngine().run(signals)

    print(f"sample_size : {report.sample_size}")
    if report.sample_size > 0 and report.clv_mean is not None:
        print(f"clv_mean    : {report.clv_mean:.4f}")
    if has_outcomes_file and report.hit_rate is not None:
        print(f"hit_rate    : {report.hit_rate:.4f}")
    if has_outcomes_file and report.roi is not None:
        print(f"roi         : {report.roi:.4f}")


def main() -> None:
    """QUANT-04: Replay odds_snapshots through BacktestEngine.

    Default mode: CLV-only (clv_mean printed, no actual outcomes needed).
    With --outcomes-file: full ROI/hit-rate mode.
    """
    parser = argparse.ArgumentParser(
        description="QUANT-04: Replay odds_snapshots through BacktestEngine"
    )
    parser.add_argument("--game-id", default=None, help="Filter to specific game_id")
    parser.add_argument(
        "--market", default=None, help="Filter to specific market_type (e.g. h2h)"
    )
    parser.add_argument(
        "--outcomes-file",
        default=None,
        help="JSON file mapping game_id -> bool outcome",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="asyncpg DSN (defaults to settings.database_url_async)",
    )
    args = parser.parse_args()

    db_url: str = args.db_url or settings.database_url_async
    outcomes: Optional[dict[str, bool]] = None
    has_outcomes_file = args.outcomes_file is not None

    if has_outcomes_file:
        outcomes = json.loads(Path(args.outcomes_file).read_text())

    asyncio.run(
        _async_main(
            db_url=db_url,
            game_id=args.game_id,
            market=args.market,
            outcomes=outcomes,
            has_outcomes_file=has_outcomes_file,
        )
    )


if __name__ == "__main__":
    import sys

    main()
    sys.exit(0)
