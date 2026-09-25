"""Opt-in read-only NBA/CFB prospective exact-price checkpoint; NFL is unchanged."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sportsbet import ledger as ledger_module
from sportsbet.ledger import utc_timestamp
from sportsbet.quant import backtest, edge_evidence, market_baseline, priced_market_audit, shadow_prior
from sportsbet.quant.audit_storage import ReadOnlyLedger, audit_database_url

PROTOCOL = {
    "version": "nba-cfb-priced-prospective-v1",
    "sports": ["nba", "cfb"],
    "captured_after": "2026-09-25T04:00:00+00:00",
    "model_version": "empirical-jeffreys-v4",
    "recommendation_policy_version": "confidence-floor-v2",
    "bootstrap_samples": 10_000,
    "minimum_paired_games": 50,
    "minimum_decided_recommendations": 100,
    "minimum_recommendation_games": 30,
}


def source_digests() -> dict:
    paths = {"runner": Path(__file__)}
    for module in (ledger_module, backtest, priced_market_audit, edge_evidence, market_baseline, shadow_prior):
        paths[module.__name__.rsplit(".", 1)[-1]] = Path(module.__file__)
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def audit_sport(ledger, sport: str, *, now: datetime | None = None) -> dict:
    """Caller must hold one ledger snapshot through checks and both cohorts."""
    if sport not in PROTOCOL["sports"]:
        raise ValueError("This protocol covers NBA and CFB separately; NFL is unchanged")
    now = now or datetime.now(timezone.utc)
    now = utc_timestamp(now.isoformat())
    cutoff = utc_timestamp(PROTOCOL["captured_after"])
    if (edge_evidence.MIN_PAIRED_GAMES, edge_evidence.MIN_DECIDED_RECOMMENDATIONS,
            edge_evidence.MIN_RECOMMENDATION_GAMES) != (50, 100, 30):
        raise ValueError("Frozen evidence thresholds changed; a new protocol is required")
    for row in ledger.predictions():
        key = priced_market_audit._eligible(row, sport, PROTOCOL["model_version"])
        if key is None or key[0] < cutoff:
            continue
        if key[0] > now:
            raise ValueError("Prospective forecast is recorded in the future")
        if row.get("recommendation_policy_version") != PROTOCOL["recommendation_policy_version"]:
            raise ValueError("Prospective cohort contains a missing or changed policy")
    reports = [priced_market_audit.audit_ledger(
        ledger, sport=sport, model_version=PROTOCOL["model_version"],
        recommendations_only=accepted, captured_after=PROTOCOL["captured_after"],
        bootstrap_samples=PROTOCOL["bootstrap_samples"],
    ) for accepted in (False, True)]
    assessment = edge_evidence.assess_prospective_edge(*reports)
    return {
        "protocol": dict(PROTOCOL),
        "protocol_sha256": hashlib.sha256(json.dumps(PROTOCOL, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest(),
        "evaluator_sha256": source_digests(),
        "sport": sport,
        "observed_at": now.isoformat(),
        "status": "awaiting_start" if now < cutoff else assessment["status"],
        "assessment": assessment,
        "cohorts": {report["cohort"]: report["prospective"] for report in reports},
        "promote": False,
        "scope": "Separate sport evidence; hypothetical recorded prices, no executed profit.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", choices=["nba", "cfb", "all"], default="all")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database-env")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    try:
        ledger = ReadOnlyLedger(database_url=audit_database_url(args.database_env))
        sports = PROTOCOL["sports"] if args.sport == "all" else [args.sport]
        with ledger.snapshot():
            now = datetime.now(timezone.utc)
            result = {sport: audit_sport(ledger, sport, now=now) for sport in sports}
        encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(json.dumps({sport: report["status"] for sport, report in result.items()}))
    except Exception as exc:
        raise SystemExit(f"NBA/CFB prospective audit unavailable: {type(exc).__name__}") from None


if __name__ == "__main__":
    main()
