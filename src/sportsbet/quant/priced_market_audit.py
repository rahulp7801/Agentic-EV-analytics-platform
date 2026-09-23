"""Compare recorded pregame prop forecasts with exact contemporaneous sportsbook prices.

Read-only. The cohort mirrors Ledger.report eligibility and earliest-selection rules;
raise on a count mismatch so future ledger policy changes cannot silently skew it.
"""
from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict
from decimal import Decimal
from statistics import mean

from sportsbet.arbitrage.ev import quote_terms
from sportsbet.ledger import (
    Ledger, normalized_model_version, quote_evidence_valid,
    settlement_identity_valid, utc_timestamp, validated_selection,
    verified_settlement_evidence,
)
from sportsbet.model_contract import QUOTE_PROVENANCE_MODEL_VERSIONS
from sportsbet.quant.market_baseline import verified_recorded_market_baseline


def _implied(odds: int) -> float:
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def _eligible(row: dict, sport: str, version: str | None) -> tuple | None:
    if row.get("sport") != sport:
        return None
    try:
        recorded_version = normalized_model_version(row)
        if version is not None and recorded_version != version:
            return None
        if not row.get("game_start_time") or not row.get("captured_at") or row.get("model_probability") is None:
            return None
        if recorded_version in QUOTE_PROVENANCE_MODEL_VERSIONS and (
            not quote_evidence_valid(row) or not settlement_identity_valid(row)
        ):
            return None
        start = utc_timestamp(row["game_start_time"])
        entered = utc_timestamp(row["captured_at"])
        quote = utc_timestamp(row.get("quote_time") or row["captured_at"])
        generated = utc_timestamp(row.get("model_generated_at") or row["captured_at"])
        probability = Decimal(str(row["model_probability"]))
        push = Decimal(str(row.get("push_probability", 0)))
        selection = validated_selection(row)[:5]
        if not probability.is_finite() or not push.is_finite() or not 0 <= probability <= 1 or not 0 <= push <= 1-probability:
            return None
        odds = row.get("american_odds")
        if type(odds) is not int or abs(odds) < 100:
            return None
        quote_terms(odds, Decimal(0))
        if entered >= start or quote > entered or generated > entered or row.get("synthetic_price") or str(row.get("sportsbook", "")).lower() == "prizepicks":
            return None
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return None
    return entered, str(row["prediction_id"]), selection


def _quote_key(row: dict) -> tuple:
    return tuple(row.get(field) for field in (
        "game_id", "player", "prop_type", "line", "sportsbook", "quote_time"))


def _settled_outcome(row: dict) -> bool | None:
    outcome = row.get("outcome")
    if type(outcome) is not bool:
        return None
    if not verified_settlement_evidence(
        row, outcome, row.get("outcome_source"), row.get("outcome_ref"),
        row.get("outcome_observed_at"), row.get("actual_value"), row.get("outcome_evidence"),
    ):
        return None
    return outcome


def compare_eligible_rows(rows: list[dict], *, bootstrap_samples: int = 10_000,
                          seed: int = 20260922) -> dict:
    """Score earliest selections; pair opposite sides at the same book and quote time."""
    if bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be nonnegative")
    ordered = sorted(rows, key=lambda row: (utc_timestamp(row["captured_at"]), str(row["prediction_id"])))
    quotes: dict[tuple, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for row in ordered:
        quotes[_quote_key(row)][row["direction"]].add(row["american_odds"])
    selected = []
    seen = set()
    for row in ordered:
        identity = validated_selection(row)[:5]
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(row)
    decided = [row for row in selected if _settled_outcome(row) is not None]
    if not decided:
        return {"source_eligible": len(rows), "earliest_selections": len(selected),
                "decided": 0, "paired_decided": 0}
    model_error = []
    raw_error = []
    flat_return = []
    paired = []
    game_deltas: dict[str, list[float]] = defaultdict(list)
    game_blend_rows: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for row in decided:
        y = int(row["outcome"])
        p = float(row["model_probability"])
        raw = _implied(row["american_odds"])
        model_error.append((p-y)**2)
        raw_error.append((raw-y)**2)
        flat_return.append((row["american_odds"]/100 if row["american_odds"] > 0 else 100/-row["american_odds"]) if y else -1)
        other = "under" if row["direction"] == "over" else "over"
        opposite_prices = quotes[_quote_key(row)].get(other, set())
        recorded = verified_recorded_market_baseline(row)
        paired_price = (raw / (raw + _implied(next(iter(opposite_prices))))
                        if len(opposite_prices) == 1 else None)
        if (recorded is not None and paired_price is not None
                and abs(recorded-paired_price) > 1e-10):
            continue
        no_vig = recorded if recorded is not None else paired_price
        if no_vig is None:
            continue
        model_brier = (p-y)**2
        market_brier = (no_vig-y)**2
        paired.append((model_brier, market_brier))
        game_id = str(row["game_id"])
        game_deltas[game_id].append(model_brier-market_brier)
        game_blend_rows[game_id].append((p, no_vig, y))
    result = {
        "source_eligible": len(rows), "earliest_selections": len(selected),
        "decided": len(decided), "pending_or_push": len(selected)-len(decided),
        "settled_games": len({str(row["game_id"]) for row in decided}),
        "model_brier": mean(model_error), "raw_implied_brier": mean(raw_error),
        "hypothetical_flat_stake_roi": mean(flat_return),
        "paired_decided": len(paired), "paired_games": len(game_deltas),
        "paired_model_brier": mean(x[0] for x in paired) if paired else None,
        "paired_market_no_vig_brier": mean(x[1] for x in paired) if paired else None,
        "paired_model_minus_market_brier": mean(x[0]-x[1] for x in paired) if paired else None,
    }
    if len(game_blend_rows) >= 2:
        held_out_errors = []
        blend_weights = []
        for game_id, test_rows in sorted(game_blend_rows.items()):
            train_rows = [item for other, values in game_blend_rows.items()
                          if other != game_id for item in values]
            denominator = sum((p-q)**2 for p, q, _ in train_rows)
            weight = (sum((y-q)*(p-q) for p, q, y in train_rows) / denominator
                      if denominator else 0.0)
            weight = min(1.0, max(0.0, weight))
            blend_weights.append(weight)
            held_out_errors.extend((q+weight*(p-q)-y)**2 for p, q, y in test_rows)
        result["market_model_leave_one_game_out_brier"] = mean(held_out_errors)
        result["leave_one_game_out_weight_range"] = [min(blend_weights), max(blend_weights)]
        result["leave_one_game_out_positive_weights"] = sum(w > 0 for w in blend_weights)
    if paired and bootstrap_samples:
        games = sorted(game_deltas)
        rng = random.Random(seed)
        draws = []
        for _ in range(bootstrap_samples):
            sample = [game_deltas[rng.choice(games)] for _ in games]
            draws.append(sum(map(sum, sample)) / sum(map(len, sample)))
        draws.sort()
        result["game_cluster_bootstrap_95"] = [
            draws[int(.025*bootstrap_samples)],
            draws[min(bootstrap_samples-1, int(.975*bootstrap_samples))],
        ]
        result["bootstrap_samples"] = bootstrap_samples
        result["bootstrap_seed"] = seed
    return result


def audit_ledger(ledger: Ledger, *, sport: str = "nfl", model_version: str | None = None,
                 bootstrap_samples: int = 10_000) -> dict:
    report = ledger.report(sport=sport, model_version=model_version)
    valid = []
    for row in ledger.predictions():
        key = _eligible(row, sport, model_version)
        if key is not None:
            valid.append((key, row))
    result = compare_eligible_rows([row for _, row in valid], bootstrap_samples=bootstrap_samples)
    if (result["earliest_selections"] != report["sample_size"]
            or result["decided"] != report["settled_count"]
            or len(valid)-result["earliest_selections"] != report["duplicate_predictions"]):
        raise ValueError("Priced audit cohort diverged from Ledger.report")
    return {"sport": sport, "model_version": model_version,
            "selection_policy": report["selection_policy"],
            "profit_scope": report["profit_scope"], **result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", default="nfl")
    parser.add_argument("--model-version")
    parser.add_argument("--database-env", default="ANALYTICS_DATABASE_URL",
                        help="Environment variable containing a ledger database URL")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    args = parser.parse_args()
    database_url = os.environ.get(args.database_env)
    ledger = Ledger(database_url=database_url) if database_url else Ledger()
    print(json.dumps(audit_ledger(ledger, sport=args.sport,
                                  model_version=args.model_version,
                                  bootstrap_samples=args.bootstrap_samples),
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
