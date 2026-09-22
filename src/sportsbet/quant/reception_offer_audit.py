"""Audit fixed-threshold NFL reception replays against archived pregame offers.

The replay forecasts were made retrospectively. Matching quotes are candidates,
not accepted picks or evidence of a pregame model prediction.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


REPLAY_FILES = (
    "nfl-week1-2025-receptions.json",
    "nfl-week2-2025-receptions.json",
    "nfl-week1-2026.json",
)
RESEARCH_LINE = Decimal("4.5")
CONFIDENCE_FLOOR = 0.6


def _aware_time(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return result


def _implied(price: int) -> float:
    if not isinstance(price, int) or isinstance(price, bool) or -100 < price < 100:
        raise ValueError("American odds must be an integer outside (-100, 100)")
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def _quote_order(quote: dict[str, Any]) -> tuple[datetime, str, str]:
    return (quote["snapped_at"], quote["sportsbook"], str(quote["id"]))


def _public_quote(quote: dict[str, Any]) -> dict[str, Any]:
    return {
        key: quote[key]
        for key in (
            "id", "game_id", "player_name", "sportsbook", "side", "line",
            "price", "snapped_at", "game_start_time", "source_provider",
            "source_sha256", "source_record_sha256",
        )
    } | {
        "line": str(quote["line"]),
        "snapped_at": quote["snapped_at"].isoformat(),
        "game_start_time": quote["game_start_time"].isoformat(),
    }


def _normalize_quotes(raw_quotes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in raw_quotes:
        try:
            quote = dict(raw)
            quote_id = str(quote["id"])
            if quote_id in seen_ids:
                raise ValueError("duplicate quote ID")
            seen_ids.add(quote_id)
            if quote.get("sport") != "nfl" or quote.get("prop_type") != "player_receptions":
                raise ValueError("different sport or market")
            if not all(str(quote.get(field) or "").strip() for field in
                       ("game_id", "player_name", "sportsbook", "source_provider",
                        "source_sha256", "source_record_sha256")):
                raise ValueError("missing quote identity or provider")
            if quote.get("side") not in ("Over", "Under"):
                raise ValueError("missing or invalid side")
            quote["line"] = Decimal(str(quote["line"]))
            if not quote["line"].is_finite() or quote["line"] < 0:
                raise ValueError("invalid line")
            _implied(quote["price"])
            quote["snapped_at"] = _aware_time(quote["snapped_at"])
            quote["game_start_time"] = _aware_time(quote["game_start_time"])
            if quote["snapped_at"] >= quote["game_start_time"]:
                raise ValueError("quote was not pregame")
            valid.append(quote)
        except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation) as exc:
            rejected.append({"id": raw.get("id"), "reason": str(exc)})
    valid.sort(key=_quote_order)
    return valid, rejected


def _normalize_replay_row(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("prop_type") != "receptions":
        raise ValueError("only reception rows are supported")
    probability = raw.get("model_probability")
    if not isinstance(probability, (int, float)) or isinstance(probability, bool) \
            or not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("replay needs a finite model probability")
    if not isinstance(raw.get("outcome"), bool):
        raise ValueError("replay needs a decided outcome")
    actual = raw.get("actual_value")
    if not isinstance(actual, int) or isinstance(actual, bool) or actual < 0:
        raise ValueError("replay needs a nonnegative reception count")
    try:
        threshold = Decimal(str(raw.get("research_threshold")))
    except InvalidOperation as exc:
        raise ValueError("replay threshold must be 4.5") from exc
    if threshold != RESEARCH_LINE:
        raise ValueError("replay threshold must be 4.5")
    if raw["outcome"] != (actual > float(RESEARCH_LINE)):
        raise ValueError("replay outcome disagrees with final count")
    if not all(str(raw.get(key) or "").strip() for key in
               ("id", "event_id", "player_name")):
        raise ValueError("replay needs event and player identity")
    row = dict(raw)
    row["game_start_time"] = _aware_time(raw["game_start_time"])
    return row


def _net_win(price: int) -> float:
    return price / 100 if price > 0 else 100 / -price


def _market_comparison(entry: dict[str, Any], same_line: list[dict[str, Any]],
                       model_probability: float, side: str,
                       actual_over: bool) -> dict[str, Any]:
    opposite = "Under" if side == "Over" else "Over"
    paired = next((quote for quote in same_line
                   if quote["side"] == opposite
                   and quote["sportsbook"] == entry["sportsbook"]
                   and quote["snapped_at"] == entry["snapped_at"]
                   and quote["game_id"] == entry["game_id"]), None)
    same_book_side = [quote for quote in same_line
                      if quote["side"] == side
                      and quote["sportsbook"] == entry["sportsbook"]
                      and quote["game_id"] == entry["game_id"]]
    last_observed = max(same_book_side, key=_quote_order)
    raw_implied = _implied(entry["price"])
    paired_implied = _implied(paired["price"]) if paired else None
    model_side_probability = model_probability if side == "Over" else 1 - model_probability
    model_won = actual_over if side == "Over" else not actual_over
    under_quote = entry if side == "Under" else paired
    return {
        "candidate_entry": _public_quote(entry),
        "model_side_probability": model_side_probability,
        "raw_break_even_probability": raw_implied,
        "paired_opposite_price": paired["price"] if paired else None,
        "market_no_vig_probability": raw_implied / (raw_implied + paired_implied)
        if paired_implied is not None else None,
        "illustrative_expected_net_per_unit":
            model_side_probability * _net_win(entry["price"]) - (1 - model_side_probability),
        "illustrative_model_profit_per_unit": _net_win(entry["price"]) if model_won else -1.0,
        "always_under_same_book_quote": _public_quote(under_quote) if under_quote else None,
        "illustrative_always_under_profit_per_unit":
            (_net_win(under_quote["price"]) if not actual_over else -1.0)
            if under_quote else None,
        "last_observed_same_book_quote": _public_quote(last_observed),
        "raw_implied_movement_to_last_observed":
            _implied(last_observed["price"]) - raw_implied,
        "scenario_note": "Half-line has no push. Returns assume the archived price was fillable and the book settled the player as active; neither is verified. Last observed quote is not a closing quote.",
    }


def audit(replays: list[dict[str, Any]], raw_quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """Return full selection coverage; never promote candidate quotes to ROI."""
    quotes, rejected_quotes = _normalize_quotes(raw_quotes)
    by_start: dict[datetime, list[dict[str, Any]]] = {}
    for quote in quotes:
        by_start.setdefault(quote["game_start_time"], []).append(quote)

    result_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    seen_replay_ids: set[str] = set()
    for replay in replays:
        cohort_rows: list[dict[str, Any]] = []
        for raw in replay["records"]:
            if raw.get("prop_type") != "receptions":
                continue
            row = _normalize_replay_row(raw)
            if row["id"] in seen_replay_ids:
                raise ValueError("duplicate replay ID")
            seen_replay_ids.add(row["id"])
            p_over = row["model_probability"]
            side = "Over" if p_over >= 0.5 else "Under"
            selected = max(p_over, 1 - p_over) >= CONFIDENCE_FLOOR
            start_quotes = by_start.get(row["game_start_time"], [])
            player_quotes = [q for q in start_quotes if q["player_name"] == row["player_name"]]
            same_line = [q for q in player_quotes if q["line"] == RESEARCH_LINE]
            matching = [q for q in same_line if q["side"] == side]
            provider_events = sorted({str(q["game_id"]) for q in player_quotes})
            if not start_quotes:
                status = "no_event_quotes"
            elif not player_quotes:
                status = "no_player_quotes"
            elif len(provider_events) != 1:
                status = "ambiguous_provider_event"
            elif not same_line:
                status = "different_line"
            elif not matching:
                status = "called_side_unavailable"
            else:
                status = "candidate_exact_offer"
            market = _market_comparison(matching[0], same_line, p_over, side, row["outcome"]) if matching and status == "candidate_exact_offer" else None
            output_row = {
                "cohort": replay["id"], "replay_id": row["id"],
                "espn_event_id": row["event_id"], "player_name": row["player_name"],
                "game_start_time": row["game_start_time"].isoformat(),
                "research_line": str(RESEARCH_LINE), "model_probability_over": p_over,
                "model_side": side, "selected_at_60_percent": selected,
                "actual_receptions": row["actual_value"],
                "model_correct": row["outcome"] if side == "Over" else not row["outcome"],
                "always_under_correct": not row["outcome"],
                "offer_status": status, "provider_event_ids": provider_events,
                "observed_offers": [_public_quote(q) for q in player_quotes],
                "market_comparison": market,
            }
            cohort_rows.append(output_row)
            result_rows.append(output_row)
        selected_rows = [r for r in cohort_rows if r["selected_at_60_percent"]]
        summaries.append({
            "cohort": replay["id"], "evaluated": len(cohort_rows),
            "selected": len(selected_rows),
            "model_correct": sum(r["model_correct"] for r in selected_rows),
            "always_under_correct": sum(r["always_under_correct"] for r in selected_rows),
            "candidate_exact_offers": sum(r["offer_status"] == "candidate_exact_offer" for r in selected_rows),
            "selected_offer_statuses": dict(sorted(Counter(r["offer_status"] for r in selected_rows).items())),
        })
    selected_rows = [r for r in result_rows if r["selected_at_60_percent"]]
    return {
        "scope": "Retrospective fixed-4.5 reception replay; provider event match is candidate-only.",
        "cohorts": summaries,
        "total": {
            "evaluated": len(result_rows), "selected": len(selected_rows),
            "model_correct": sum(r["model_correct"] for r in selected_rows),
            "always_under_correct": sum(r["always_under_correct"] for r in selected_rows),
            "candidate_exact_offers": sum(r["offer_status"] == "candidate_exact_offer" for r in selected_rows),
            "all_evaluated_candidate_exact_offers": sum(r["offer_status"] == "candidate_exact_offer" for r in result_rows),
            "selected_offer_statuses": dict(sorted(Counter(r["offer_status"] for r in selected_rows).items())),
            "valid_quote_rows": len(quotes), "rejected_quote_rows": len(rejected_quotes),
        },
        "priced_strategy": {
            "verified_pregame_model_and_event_matches": 0,
            "roi": None, "calibration_against_offers": None,
            "clv": None, "game_cluster_interval": None, "player_cluster_interval": None,
            "reason": "Replay predictions lack pregame generation timestamps; provider event crosswalk, fill, and settlement rules are unverified.",
        },
        "rejected_quotes": rejected_quotes,
        "rows": result_rows,
    }


async def _load_database_quotes(first: datetime, last: datetime) -> list[dict[str, Any]]:
    import asyncpg
    from dotenv import dotenv_values

    dsn = dotenv_values(".env").get("DATABASE_URL_ASYNC")
    if not dsn:
        raise ValueError("DATABASE_URL_ASYNC is not configured in .env")
    conn = await asyncpg.connect(dsn.replace("postgresql+asyncpg://", "postgresql://"), timeout=15)
    try:
        await conn.execute("SET default_transaction_read_only = on")
        rows = await conn.fetch(
            "SELECT id,sport,game_id,player_name,sportsbook,prop_type,line,price,side,"
            "game_start_time,snapped_at,source_provider,source_sha256,source_record_sha256 "
            "FROM player_prop_snapshots WHERE sport='nfl' AND prop_type='player_receptions' "
            "AND game_start_time >= $1 AND game_start_time <= $2 ORDER BY snapped_at,id",
            first, last,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", type=Path, default=Path("frontend/data"))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", action="store_true", help="Read restricted PostgreSQL quotes without writing")
    source.add_argument("--quotes-file", type=Path, help="Offline JSON array of quote rows")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, help="Write a compact, reviewable JSON summary")
    args = parser.parse_args()
    if args.summary_output and args.summary_output.resolve() == args.output.resolve():
        parser.error("--summary-output must differ from --output")

    replays = []
    replay_hashes = {}
    for name in REPLAY_FILES:
        raw = (args.replay_dir / name).read_bytes()
        replay_hashes[name] = hashlib.sha256(raw).hexdigest()
        replays.append(json.loads(raw.decode("utf-8-sig")))
    if args.quotes_file:
        raw_quotes = args.quotes_file.read_bytes()
        quotes = json.loads(raw_quotes.decode("utf-8-sig"))
        quote_hash = hashlib.sha256(raw_quotes).hexdigest()
    else:
        starts = [_aware_time(row["game_start_time"]) for replay in replays
                  for row in replay["records"] if row.get("prop_type") == "receptions"]
        quotes = asyncio.run(_load_database_quotes(min(starts), max(starts)))
        quote_hash = hashlib.sha256(json.dumps(quotes, sort_keys=True, default=str).encode()).hexdigest()
    report = audit(replays, quotes)
    report["input_sha256"] = {"replays": replay_hashes, "quotes": quote_hash}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.summary_output:
        summary = {key: report[key] for key in ("scope", "input_sha256", "cohorts", "total", "priced_strategy")}
        summary["candidate_rows"] = [
            {key: row[key] for key in ("cohort", "replay_id", "espn_event_id",
                                       "player_name", "game_start_time", "model_side",
                                       "selected_at_60_percent", "actual_receptions",
                                       "model_correct", "always_under_correct",
                                       "market_comparison")}
            for row in report["rows"] if row["offer_status"] == "candidate_exact_offer"
        ]
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "total": report["total"],
                      "priced_strategy": report["priced_strategy"]}, indent=2))


if __name__ == "__main__":
    main()
