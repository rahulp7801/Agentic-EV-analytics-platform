"""Leakage-safe NFL Next Gen Stats ablation against the production baseline.

The experiment uses rolling, half-point research thresholds because free historical
sportsbook prices are unavailable.  It measures forecast calibration, not betting
profit.  Candidate models are selected and fitted before the untouched evaluation
season; target-game NGS rows never enter their features.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import sqlalchemy as sa

from sportsbet.db.connection import get_sync_engine
from sportsbet.quant.backtest import calibration_metrics, game_cluster_score_metrics

MIN_HISTORY = 20
MAX_HISTORY = 40
MAX_NGS_WEEKS = 8
BOOTSTRAP_REPETITIONS = 2_000
TEAM_ALIASES = {"LA": "LAR", "WAS": "WSH"}
Row = dict[str, Any]
PROP_CONFIG = {
    "pass_yds": ("passing_yards", "passing", (
        "avg_time_to_throw", "avg_completed_air_yards",
        "avg_intended_air_yards", "aggressiveness",
    )),
    "rush_yds": ("rushing_yards", "rushing", (
        "efficiency", "percent_attempts_gte_eight_defenders",
        "rush_yards_over_expected", "avg_time_to_los",
    )),
    "rec_yds": ("receiving_yards", "receiving", (
        "avg_separation", "avg_cushion", "avg_yac_above_expectation",
    )),
    "receptions": ("receptions", "receiving", (
        "avg_separation", "avg_cushion", "avg_yac_above_expectation",
    )),
}


@dataclass(frozen=True)
class Example:
    season: int
    week: int
    game_id: str
    player_id: str
    prop_type: str
    threshold: float
    outcome: int
    base_probability: float
    ngs_features: tuple[float, ...]


@dataclass(frozen=True)
class FittedAdjustment:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]

    def predict(self, example: Example) -> float:
        values = tuple(
            (value - mean) / scale
            for value, mean, scale in zip(
                example.ngs_features, self.means, self.scales, strict=True
            )
        )
        offset = _logit(example.base_probability)
        score = offset + self.coefficients[0] + sum(
            coefficient * value
            for coefficient, value in zip(self.coefficients[1:], values, strict=True)
        )
        return _sigmoid(score)


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-min(value, 30.0))
        return 1.0 / (1.0 + inverse)
    exponent = math.exp(max(value, -30.0))
    return exponent / (1.0 + exponent)


def _logit(probability: float) -> float:
    bounded = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(bounded / (1 - bounded))


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a small dense linear system with pivoted Gaussian elimination."""
    size = len(vector)
    augmented = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-10:
            raise ValueError("Candidate model is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                current - factor * source
                for current, source in zip(augmented[row], augmented[column], strict=True)
            ]
    return [augmented[row][-1] for row in range(size)]


def fit_adjustment(examples: Sequence[Example], penalty: float = 1.0) -> FittedAdjustment:
    """Fit a deterministic L2 logistic adjustment with the base logit as offset."""
    if len(examples) < 2 or penalty <= 0:
        raise ValueError("Candidate fitting needs at least two examples and positive penalty")
    width = len(examples[0].ngs_features)
    if not width or any(len(example.ngs_features) != width for example in examples):
        raise ValueError("Candidate features are inconsistent")
    columns = list(zip(*(example.ngs_features for example in examples), strict=True))
    means = tuple(statistics.fmean(column) for column in columns)
    scales = tuple(max(statistics.pstdev(column), 1e-9) for column in columns)
    design = [
        (1.0,) + tuple(
            (value - mean) / scale
            for value, mean, scale in zip(
                example.ngs_features, means, scales, strict=True
            )
        )
        for example in examples
    ]
    coefficients = [0.0] * (width + 1)
    for _ in range(60):
        gradient = [0.0] * len(coefficients)
        hessian = [[0.0] * len(coefficients) for _ in coefficients]
        for example, features in zip(examples, design, strict=True):
            probability = _sigmoid(
                _logit(example.base_probability)
                + sum(a * b for a, b in zip(coefficients, features, strict=True))
            )
            residual = probability - example.outcome
            weight = max(probability * (1 - probability), 1e-8)
            for left, left_value in enumerate(features):
                gradient[left] += residual * left_value
                for right, right_value in enumerate(features):
                    hessian[left][right] += weight * left_value * right_value
        for index in range(1, len(coefficients)):
            gradient[index] += penalty * coefficients[index]
            hessian[index][index] += penalty
        hessian[0][0] += 1e-8
        step = _solve(hessian, gradient)
        coefficients = [value - change for value, change in zip(coefficients, step, strict=True)]
        if max(abs(change) for change in step) < 1e-8:
            break
    if any(not math.isfinite(value) for value in coefficients):
        raise ValueError("Candidate fitting did not converge")
    return FittedAdjustment(means, scales, tuple(coefficients))


def _valid_source(row: Row, provider: str) -> bool:
    observed = row.get("source_observed_at")
    return (
        row.get("source_provider") == provider
        and isinstance(row.get("source_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]) is not None
        and isinstance(row.get("source_record_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", row["source_record_sha256"]) is not None
        and isinstance(observed, datetime)
        and observed.utcoffset() is not None
    )


def _key(season: int, week: int) -> tuple[int, int]:
    return season, week


def build_examples(
    player_rows: Sequence[Row],
    ngs_rows: Sequence[Row],
    games: Sequence[Row],
    prop_type: str,
    target_seasons: set[int],
) -> tuple[list[Example], dict[str, Any]]:
    """Build point-in-time examples; every feature row precedes its target week."""
    if prop_type not in PROP_CONFIG or not target_seasons:
        raise ValueError("Unsupported ablation request")
    stat_column, stat_type, metric_names = PROP_CONFIG[prop_type]
    schedule: dict[tuple[int, int, str], list[str]] = defaultdict(list)
    for game in games:
        for raw_team in (game["home_team"], game["away_team"]):
            if not isinstance(raw_team, str):
                continue
            team = TEAM_ALIASES.get(raw_team, raw_team)
            schedule[(int(game["season"]), int(game["week"]), team)].append(
                str(game["game_id"])
            )
    stats: dict[str, list[Row]] = defaultdict(list)
    for row in player_rows:
        if _valid_source(row, "nflverse") and row.get(stat_column) is not None:
            stats[row["player_id"]].append(row)
    tracking: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in ngs_rows:
        if row.get("stat_type") == stat_type and _valid_source(row, "nflverse_ngs"):
            tracking[(row["player_gsis_id"], stat_type)].append(row)
    for rows in (*stats.values(), *tracking.values()):
        rows.sort(key=lambda row: _key(row["season"], row["week"]))

    examples: list[Example] = []
    excluded: defaultdict[str, int] = defaultdict(int)
    history_eligible: defaultdict[int, int] = defaultdict(int)
    tracking_complete: defaultdict[int, int] = defaultdict(int)
    for player_id, rows in stats.items():
        ngs = tracking.get((player_id, stat_type), [])
        for target in rows:
            if target["season"] not in target_seasons:
                continue
            target_key = _key(target["season"], target["week"])
            history = [
                row for row in rows
                if _key(row["season"], row["week"]) < target_key
                and row["season"] >= target["season"] - 2
            ][-MAX_HISTORY:]
            if len(history) < MIN_HISTORY:
                excluded["insufficient_history"] += 1
                continue
            raw_team = target.get("team")
            if not isinstance(raw_team, str):
                excluded["missing_or_ambiguous_game"] += 1
                continue
            team = TEAM_ALIASES.get(raw_team, raw_team)
            game_ids = schedule.get((target["season"], target["week"], team), [])
            if len(game_ids) != 1:
                excluded["missing_or_ambiguous_game"] += 1
                continue
            history_eligible[target["season"]] += 1
            prior_ngs = [
                row for row in ngs
                if _key(row["season"], row["week"]) < target_key
                and row["season"] >= target["season"] - 1
            ][-MAX_NGS_WEEKS:]
            if not prior_ngs:
                excluded["missing_tracking_history"] += 1
                continue
            feature_values: list[float] = []
            for metric in metric_names:
                values = [float(row[metric]) for row in prior_ngs if row.get(metric) is not None]
                if not values or any(not math.isfinite(value) for value in values):
                    break
                feature_values.append(statistics.fmean(values))
            if len(feature_values) != len(metric_names):
                excluded["incomplete_tracking_features"] += 1
                continue
            values = [float(row[stat_column]) for row in history]
            threshold = math.floor(statistics.median(values)) + 0.5
            successes = sum(value > threshold for value in values)
            base_probability = (successes + 0.5) / (len(values) + 1)
            actual = float(target[stat_column])
            if not math.isfinite(actual):
                excluded["invalid_outcome"] += 1
                continue
            examples.append(Example(
                season=target["season"], week=target["week"], game_id=game_ids[0],
                player_id=player_id, prop_type=prop_type, threshold=threshold,
                outcome=int(actual > threshold), base_probability=base_probability,
                ngs_features=tuple(feature_values),
            ))
            tracking_complete[target["season"]] += 1
    examples.sort(key=lambda row: (row.season, row.week, row.game_id, row.player_id))
    coverage = {}
    for season in sorted(target_seasons):
        eligible = history_eligible[season]
        complete = tracking_complete[season]
        coverage[str(season)] = {
            "history_eligible": eligible,
            "tracking_complete": complete,
            "tracking_missing": eligible - complete,
            "tracking_coverage": complete / eligible if eligible else 0.0,
        }
    return examples, {
        "coverage_by_season": coverage,
        "excluded": dict(sorted(excluded.items())),
    }


def _score(predictions: Sequence[tuple[str, float, int]]) -> dict[str, Any]:
    plain = [(probability, outcome) for _, probability, outcome in predictions]
    return calibration_metrics(plain) | game_cluster_score_metrics(list(predictions))


def _bootstrap_intervals(
    paired: Sequence[tuple[str, float, float, int]], seed: int = 20260921
) -> dict[str, list[float]]:
    clusters: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for game_id, base_probability, candidate_probability, outcome in paired:
        clusters[game_id].append((base_probability, candidate_probability, outcome))
    identities = sorted(clusters)
    if len(identities) < 2:
        return {}
    summaries: dict[str, dict[str, Any]] = {}
    for identity, rows in clusters.items():
        summary: dict[str, Any] = {
            "count": len(rows),
            "base_brier_score": sum((probability - outcome) ** 2 for probability, _, outcome in rows),
            "candidate_brier_score": sum((probability - outcome) ** 2 for _, probability, outcome in rows),
            "base_log_loss": sum(
                -(outcome * math.log(max(1e-15, probability))
                  + (1 - outcome) * math.log(max(1e-15, 1 - probability)))
                for probability, _, outcome in rows
            ),
            "candidate_log_loss": sum(
                -(outcome * math.log(max(1e-15, probability))
                  + (1 - outcome) * math.log(max(1e-15, 1 - probability)))
                for _, probability, outcome in rows
            ),
            "base_bins": [[0.0, 0.0] for _ in range(10)],
            "candidate_bins": [[0.0, 0.0] for _ in range(10)],
        }
        for base_probability, candidate_probability, outcome in rows:
            for name, probability in (
                ("base_bins", base_probability),
                ("candidate_bins", candidate_probability),
            ):
                bucket = min(9, int(probability * 10))
                summary[name][bucket][0] += probability
                summary[name][bucket][1] += outcome
        summaries[identity] = summary
    rng = random.Random(seed)
    draws: dict[str, list[float]] = defaultdict(list)
    for _ in range(BOOTSTRAP_REPETITIONS):
        sample = [rng.choice(identities) for _ in identities]
        total = sum(summaries[identity]["count"] for identity in sample)
        metrics: dict[str, float] = {}
        for model in ("base", "candidate"):
            for metric in ("brier_score", "log_loss"):
                metrics[f"{model}_{metric}"] = sum(
                    summaries[identity][f"{model}_{metric}"] for identity in sample
                ) / total
            bins = [[0.0, 0.0] for _ in range(10)]
            for identity in sample:
                for bucket, values in enumerate(summaries[identity][f"{model}_bins"]):
                    bins[bucket][0] += values[0]
                    bins[bucket][1] += values[1]
            metrics[f"{model}_calibration_error"] = sum(
                abs(probability_sum - outcome_sum)
                for probability_sum, outcome_sum in bins
            ) / total
        for metric in ("brier_score", "log_loss", "calibration_error"):
            base_value = metrics[f"base_{metric}"]
            candidate_value = metrics[f"candidate_{metric}"]
            draws[f"base_{metric}"].append(base_value)
            draws[f"candidate_{metric}"].append(candidate_value)
            draws[f"difference_{metric}"].append(candidate_value - base_value)

    def percentile(values: list[float], quantile: float) -> float:
        ordered = sorted(values)
        location = (len(ordered) - 1) * quantile
        lower = math.floor(location)
        upper = math.ceil(location)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (location - lower)

    return {
        name: [percentile(values, 0.025), percentile(values, 0.975)]
        for name, values in sorted(draws.items())
    }


def evaluate_prop(
    examples: Sequence[Example], train_season: int, evaluation_season: int
) -> dict[str, Any]:
    train = [example for example in examples if example.season == train_season]
    evaluation = [example for example in examples if example.season == evaluation_season]
    if len(train) < 100 or len(evaluation) < 100:
        return {
            "status": "insufficient_sample", "training_count": len(train),
            "evaluation_count": len(evaluation), "promote": False,
        }
    fitted = fit_adjustment(train)
    paired = [
        (example.game_id, example.base_probability, fitted.predict(example), example.outcome)
        for example in evaluation
    ]
    base = _score([(game, base, outcome) for game, base, _, outcome in paired])
    candidate = _score([(game, probability, outcome) for game, _, probability, outcome in paired])
    intervals = _bootstrap_intervals(paired)
    differences = {
        metric: candidate[metric] - base[metric]
        for metric in ("brier_score", "log_loss", "calibration_error")
    }
    promote = all((
        differences["brier_score"] < 0,
        differences["log_loss"] < 0,
        differences["calibration_error"] <= 0,
        intervals["difference_brier_score"][1] < 0,
        intervals["difference_log_loss"][1] < 0,
        intervals["difference_calibration_error"][1] <= 0,
    ))
    return {
        "status": "evaluated", "training_count": len(train),
        "evaluation_count": len(evaluation),
        "evaluation_game_clusters": len({example.game_id for example in evaluation}),
        "base": base, "candidate": candidate, "candidate_minus_base": differences,
        "game_cluster_bootstrap_intervals": intervals,
        "bootstrap_method": (
            f"95% percentile interval; {BOOTSTRAP_REPETITIONS} deterministic resamples "
            "of whole game clusters"
        ),
        "feature_means": list(fitted.means), "feature_scales": list(fitted.scales),
        "coefficients": list(fitted.coefficients), "promote": promote,
    }


def load_source_rows(
    engine: sa.Engine, start_season: int, end_season: int
) -> tuple[list[Row], list[Row], list[Row]]:
    """Read the bounded, provenance-bearing research corpus with static SQL."""
    if not 2016 <= start_season <= end_season <= 2100:
        raise ValueError("Invalid season window")
    with engine.connect() as connection:
        players = connection.execute(sa.text("""
            SELECT player_id,season,week,team,passing_yards,rushing_yards,
                   receiving_yards,receptions,source_provider,source_sha256,
                   source_record_sha256,source_observed_at
            FROM player_stats WHERE season BETWEEN :start AND :finish
        """), {"start": start_season, "finish": end_season}).mappings().all()
        ngs = connection.execute(sa.text("""
            SELECT player_gsis_id,season,week,stat_type,avg_time_to_throw,
                   avg_completed_air_yards,avg_intended_air_yards,aggressiveness,
                   avg_separation,avg_cushion,avg_yac_above_expectation,efficiency,
                   percent_attempts_gte_eight_defenders,rush_yards_over_expected,
                   avg_time_to_los,source_provider,source_sha256,
                   source_record_sha256,source_observed_at
            FROM ngs_stats WHERE season BETWEEN :start AND :finish
        """), {"start": start_season, "finish": end_season}).mappings().all()
        games = connection.execute(sa.text("""
            SELECT game_id,season,week,home_team,away_team FROM games
            WHERE season BETWEEN :start AND :finish
        """), {"start": start_season, "finish": end_season}).mappings().all()
    return [dict(row) for row in players], [dict(row) for row in ngs], [dict(row) for row in games]


def evaluate(
    player_rows: Sequence[Row], ngs_rows: Sequence[Row], games: Sequence[Row],
    *, train_season: int, evaluation_season: int,
) -> dict[str, Any]:
    if evaluation_season != train_season + 1:
        raise ValueError("Evaluation season must immediately follow training season")
    reports: dict[str, dict[str, Any]] = {}
    for prop_type, (_, _, features) in PROP_CONFIG.items():
        examples, cohort = build_examples(
            player_rows, ngs_rows, games, prop_type, {train_season, evaluation_season}
        )
        reports[prop_type] = evaluate_prop(examples, train_season, evaluation_season) | {
            "features": list(features), **cohort,
        }
    promoted = sorted(prop for prop, report in reports.items() if report["promote"])
    return {
        "experiment": "nfl_ngs_probability_ablation_v1",
        "training_season": train_season,
        "untouched_evaluation_season": evaluation_season,
        "decision": "eligible_for_model_review" if promoted else "retain_as_evidence_only",
        "promoted_prop_types": promoted,
        "probability_adjustments_applied": False,
        "props": reports,
        "limitations": [
            "Half-point rolling median research thresholds are not archived sportsbook lines.",
            "This evaluates forecast calibration only; ROI, CLV, profit, and win-rate claims are unavailable.",
            "Features use at most eight prior NGS weeks and outcomes use at most forty prior games.",
            "Model fitting uses only the prior season; the evaluation season does not select or fit candidates.",
            "The cohort requires prior tracking and history; it does not reconstruct which players sportsbooks offered.",
            "Promotion requires paired game-cluster intervals to improve Brier and log loss without worse calibration.",
        ],
    }


def _code_sha256() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-season", type=int, required=True)
    parser.add_argument("--evaluation-season", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    players, ngs, games = load_source_rows(
        get_sync_engine(), args.train_season - 2, args.evaluation_season
    )
    report = evaluate(
        players, ngs, games, train_season=args.train_season,
        evaluation_season=args.evaluation_season,
    )
    report["source_code_sha256"] = _code_sha256()
    report["source_rows"] = {
        "player_stats": len(players), "ngs_stats": len(ngs), "games": len(games),
    }
    report["source_commitments"] = {
        "player_stats": sorted({
            f"{row['season']}:{row['source_sha256']}"
            for row in players if _valid_source(row, "nflverse")
        }),
        "ngs_stats": sorted({
            f"{row['season']}:{row['stat_type']}:{row['source_sha256']}"
            for row in ngs if _valid_source(row, "nflverse_ngs")
        }),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
