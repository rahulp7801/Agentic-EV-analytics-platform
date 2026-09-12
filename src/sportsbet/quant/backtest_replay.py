"""Replay same-selection quotes. Legacy rows missing identity/start time are excluded."""
from __future__ import annotations
import argparse
import asyncio
import json
import hashlib
from dataclasses import fields
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
    ids: set[str] = set()
    for row in rows:
        if row.get("id") is None or str(row["id"]) in ids:
            raise ValueError("Every snapshot must have a unique ID")
        ids.add(str(row["id"]))
        start, captured = row.get("game_start_time"), row.get("snapped_at")
        if not all((row.get("game_id"), row.get("outcome_name"), row.get("sportsbook"), row.get("market_type"), start, captured)):
            continue
        if start.tzinfo is None or captured.tzinfo is None:
            raise ValueError("Quote timestamps must include a timezone")
        if captured >= start or row.get("price") in (None, 0):
            continue
        # An Over/Under quote without its line (or player for a prop) cannot
        # identify a settlement or be compared with another quote safely.
        if row["outcome_name"].lower() in ("over", "under"):
            if row.get("line") is None:
                continue
            if row["market_type"] not in ("totals", "alternate_totals") and not row.get("player_name"):
                continue
        if row.get("line") is not None and not Decimal(str(row["line"])).is_finite():
            raise ValueError("Market line must be finite")
        key = (row["game_id"], row["sportsbook"], row["market_type"], row["outcome_name"],
               row.get("player_name"), row.get("line"), start)
        groups.setdefault(key, []).append(row)
    result = []
    for group in groups.values():
        group.sort(key=lambda r: (r["snapped_at"], str(r["id"])))
        entry, close = group[0], group[-1]
        p = entry.get("model_probability")
        if p is not None:
            predicted = entry.get("model_generated_at")
            if not entry.get("model_version") or predicted is None:
                raise ValueError("Model probabilities require model_version and model_generated_at")
            if predicted.tzinfo is None or predicted.utcoffset() is None or predicted > entry["snapped_at"]:
                raise ValueError("Model prediction must be timezone-aware and no later than entry")
        result.append(BacktestSignal(
            quant_result=QuantResult(true_probability=Decimal(str(p)) if p is not None else None),
            entry_implied_prob=_american_to_implied_prob(entry["price"]),
            closing_implied_prob=_american_to_implied_prob(close["price"]),
            actual_outcome=(outcomes or {}).get(str(entry["id"])),
            stake=Decimal(str(entry.get("stake", 1))),
            payout_multiplier=_american_to_payout(entry["price"]),
            game_start_time=entry["game_start_time"], snapshot_time=close["snapped_at"],
            entry_time=entry["snapped_at"],
            push_probability=Decimal(str(entry.get("push_probability", 0))),
            game_cluster_id=entry["game_id"],
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshots-file", help="JSON quote rows with identity and ISO timestamps; avoids DB access")
    source.add_argument("--database", action="store_true", help="Read recorded quotes using DATABASE_URL_ASYNC")
    source.add_argument("--db-url", help="Explicit database URL; prefer --database to keep credentials out of shell history")
    args = parser.parse_args()
    input_hashes = {}
    if args.snapshots_file:
        raw = Path(args.snapshots_file).read_bytes()
        input_hashes["snapshots_sha256"] = hashlib.sha256(raw).hexdigest()
        rows = json.loads(raw.decode("utf-8-sig"))
        for row in rows:
            for key in ("game_start_time", "snapped_at", "model_generated_at"):
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
        try:
            rows = asyncio.run(load())
        except Exception:
            parser.exit(2, "Historical database read failed; verify connectivity and migrated schema. No backtest was produced.\n")
    if args.snapshots_file:
        rows = [r for r in rows if (args.game_id is None or r.get("game_id") == args.game_id)
                and (args.market is None or r.get("market_type") == args.market)]
    outcomes = None
    if args.outcomes_file:
        raw = Path(args.outcomes_file).read_bytes()
        input_hashes["outcomes_sha256"] = hashlib.sha256(raw).hexdigest()
        outcomes = json.loads(raw.decode("utf-8-sig"))
    signals = build_signals(rows, outcomes)
    report = BacktestEngine().run(signals)
    output = {f.name: getattr(report, f.name) for f in fields(report) if f.name != "signals_df"}
    output.update(input_hashes)
    output.update(input_quote_count=len(rows),
        evaluation_scope="Supplied selection replay; not a historical run of the current model or proof of profitability.",
        stake_note="One unit per selection unless an explicit stake is supplied; not executed bets.",
        model_versions=sorted({r["model_version"] for r in rows if r.get("model_probability") is not None and r.get("model_version")}),
        status="no_usable_quotes" if not signals else ("no_settlements" if not report.settled_count else "settled_replay"))
    print(json.dumps(output, indent=2, allow_nan=False))
    if not signals:
        parser.exit(2, "No usable historical quotes; no performance result is available.\n")


if __name__ == "__main__":
    main()
