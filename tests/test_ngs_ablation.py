from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsbet.quant.ngs_ablation import (
    Example,
    build_examples,
    evaluate_prop,
    fit_adjustment,
)

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)
HASH = "a" * 64


def player(week: int, value: int) -> dict:
    return {
        "player_id": "00-0000001", "season": 2024, "week": week, "team": "KC",
        "passing_yards": value, "rushing_yards": 0, "receiving_yards": 0,
        "receptions": 0, "source_provider": "nflverse", "source_sha256": HASH,
        "source_record_sha256": HASH, "source_observed_at": NOW,
    }


def tracking(week: int, value: float) -> dict:
    return {
        "player_gsis_id": "00-0000001", "season": 2024, "week": week,
        "stat_type": "passing", "avg_time_to_throw": value,
        "avg_completed_air_yards": value, "avg_intended_air_yards": value,
        "aggressiveness": value, "source_provider": "nflverse_ngs",
        "source_sha256": HASH, "source_record_sha256": HASH,
        "source_observed_at": NOW,
    }


def test_build_examples_uses_only_prior_rows_and_exact_game_cluster():
    rows = [player(week, 100 + week) for week in range(1, 22)]
    ngs = [tracking(week, float(week)) for week in range(1, 22)]
    games = [
        {"game_id": f"game-{week}", "season": 2024, "week": week,
         "home_team": "KC", "away_team": "LV"}
        for week in range(1, 22)
    ]
    examples, cohort = build_examples(rows, ngs, games, "pass_yds", {2024})
    assert len(examples) == 1
    example = examples[0]
    assert example.week == 21 and example.game_id == "game-21"
    assert example.threshold == 110.5
    assert example.base_probability == pytest.approx(10.5 / 21)
    assert example.ngs_features == pytest.approx((16.5,) * 4)
    assert cohort == {
        "coverage_by_season": {"2024": {
            "history_eligible": 1, "tracking_complete": 1,
            "tracking_missing": 0, "tracking_coverage": 1.0,
        }},
        "excluded": {"insufficient_history": 20},
    }


def test_target_week_tracking_never_enters_features():
    rows = [player(week, week) for week in range(1, 22)]
    ngs = [tracking(week, 1.0) for week in range(1, 21)] + [tracking(21, 999.0)]
    games = [{"game_id": "target", "season": 2024, "week": 21,
              "home_team": "KC", "away_team": "LV"}]
    examples, _ = build_examples(rows, ngs, games, "pass_yds", {2024})
    assert examples[0].ngs_features == (1.0,) * 4


def test_uncommitted_tracking_rows_fail_closed():
    rows = [player(week, week) for week in range(1, 22)]
    ngs = [tracking(week, 1.0) | {"source_sha256": "invalid"}
           for week in range(1, 21)]
    games = [{"game_id": "target", "season": 2024, "week": 21,
              "home_team": "KC", "away_team": "LV"}]
    examples, cohort = build_examples(rows, ngs, games, "pass_yds", {2024})
    assert examples == []
    assert cohort["coverage_by_season"]["2024"] == {
        "history_eligible": 1, "tracking_complete": 0,
        "tracking_missing": 1, "tracking_coverage": 0.0,
    }
    assert cohort["excluded"]["missing_tracking_history"] == 1


def test_adjustment_is_fitted_without_evaluation_outcomes():
    examples = [
        Example(2024, index, f"train-{index}", str(index), "pass_yds", 0.5,
                index % 2, 0.5, (float(index % 2),))
        for index in range(1, 121)
    ]
    first = fit_adjustment(examples)
    changed_holdout = examples + [
        Example(2025, 1, "holdout", "x", "pass_yds", 0.5, 0, 0.5, (100.0,))
    ]
    second = fit_adjustment([row for row in changed_holdout if row.season == 2024])
    assert second == first
    assert first.predict(examples[0]) > first.predict(examples[1])


def test_small_ablation_fails_closed():
    examples = [
        Example(2024, 1, "train", "p", "pass_yds", 0.5, 1, 0.5, (1.0,)),
        Example(2025, 1, "eval", "p", "pass_yds", 0.5, 1, 0.5, (1.0,)),
    ]
    report = evaluate_prop(examples, 2024, 2025)
    assert report == {
        "status": "insufficient_sample", "training_count": 1,
        "evaluation_count": 1, "promote": False,
    }
