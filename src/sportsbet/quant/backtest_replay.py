"""Replay same-selection quotes. Legacy rows missing identity/start time are excluded."""
from __future__ import annotations
import argparse
import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import asyncpg
from sportsbet.arbitrage.ev import quote_terms
from sportsbet.config import settings
from sportsbet.graph.models import QuantResult
from sportsbet.quant.backtest import BacktestEngine, BacktestSignal, Outcome


def _american_to_implied_prob(price: int) -> Decimal:
    return quote_terms(price, Decimal(0))[0]


def _american_to_payout(price: int) -> Decimal:
    return quote_terms(price, Decimal(0))[1] + 1


def build_signals(rows: list[dict], outcomes: dict[str, Outcome] | None = None) -> list[BacktestSignal]:
    """One entry per exact market identity, using earliest and latest pre-game quotes.

    outcomes is keyed by ENTRY SNAPSHOT ID, not game ID (opposite sides differ).
    Prices are raw vig-inclusive quotes, so CLV is raw probability movement.
    Missing model probabilities remain missing: quote movement is not calibration.
    """
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        start, captured = row.get("game_start_time"), row.get("snapped_at")
        if not all((row.get("game_id"), row.get("outcome_name"), row.get("sportsbook"), row.get("market_type"), start, captured)):
            continue
        if start.tzinfo is None or captured.tzinfo is None:
            raise ValueError("Quote timestamps must include a timezone")
        if captured >= start or row.get("price") in (None, 0):
            continue
        key = (row["game_id"], row["sportsbook"], row["market_type"], row["outcome_name"],
               row.get("player_name"), row.get("line"), start)
        groups.setdefault(key, []).append(row)
    result = []
    for group in groups.values():
        group.sort(key=lambda r: (r["snapped_at"], str(r["id"])))
        entry, close = group[0], group[-1]
        p = entry.get("model_probability")
        result.append(BacktestSignal(
            quant_result=QuantResult(true_probability=Decimal(str(p)) if p is not None else None),
            entry_implied_prob=_american_to_implied_prob(entry["price"]),
            closing_implied_prob=_american_to_implied_prob(close["price"]),
            actual_outcome=(outcomes or {}).get(str(entry["id"])),
            stake=Decimal(str(entry.get("stake", 1))),
            payout_multiplier=_american_to_payout(entry["price"]),
            game_start_time=entry["game_start_time"], snapshot_time=close["snapped_at"],
            entry_time=entry["snapped_at"],
        ))
    return result


async def load_snapshots(conn: asyncpg.Connection, game_id: str | None = None, market_type: str | None = None) -> list[dict]:
    clauses = ["game_id IS NOT NULL", "outcome_name IS NOT NULL", "game_start_time IS NOT NULL",
               "snapped_at < game_start_time", "price IS NOT NULL"]
    args = []
    for column, value in (("game_id", game_id), ("market_type", market_type)):
        if value is not None:
            args.append(value)
            clauses.append(f"{column} = ${len(args)}")
    rows = await conn.fetch("SELECT id, game_id, sportsbook, market_type, outcome_name, line, price, "
        "snapped_at, game_start_time FROM odds_snapshots WHERE " + " AND ".join(clauses) + " ORDER BY snapped_at", *args)
    return [dict(row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id")
    parser.add_argument("--market")
    parser.add_argument("--outcomes-file", help="JSON mapping entry snapshot ID to true/false/push/void/null")
    parser.add_argument("--snapshots-file", help="JSON quote rows with identity and ISO timestamps; avoids DB access")
    parser.add_argument("--db-url")
    args = parser.parse_args()
    if args.snapshots_file:
        rows = json.loads(Path(args.snapshots_file).read_text(encoding="utf-8-sig"))
        for row in rows:
            for key in ("game_start_time", "snapped_at"):
                if row.get(key):
                    row[key] = datetime.fromisoformat(row[key])
    else:
        async def load():
            dsn = (args.db_url or settings.database_url_async).replace("postgresql+asyncpg://", "postgresql://")
            conn = await asyncpg.connect(dsn, timeout=15)
            try:
                return await load_snapshots(conn, args.game_id, args.market)
            finally:
                await conn.close()
        rows = asyncio.run(load())
    outcomes = json.loads(Path(args.outcomes_file).read_text(encoding="utf-8-sig")) if args.outcomes_file else None
    report = BacktestEngine().run(build_signals(rows, outcomes))
    from dataclasses import fields
    print(json.dumps({f.name: getattr(report, f.name) for f in fields(report) if f.name != "signals_df"}, indent=2))


if __name__ == "__main__":
    main()
