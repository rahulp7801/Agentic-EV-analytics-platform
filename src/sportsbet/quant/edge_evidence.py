"""Predeclared evidence gate for hypothetical prospective NFL prop results."""
from __future__ import annotations


MIN_PAIRED_GAMES = 50
MIN_DECIDED_RECOMMENDATIONS = 100
MIN_RECOMMENDATION_GAMES = 30


def assess_prospective_edge(all_forecasts: dict, recommendations: dict) -> dict:
    """Apply the frozen protocol without fitting a threshold to observed results."""
    identity = ("sport", "model_version", "captured_after")
    if (all_forecasts.get("cohort") != "all_predictions"
            or recommendations.get("cohort") != "recommendations"
            or any(all_forecasts.get(key) != recommendations.get(key) for key in identity)
            or any(not all_forecasts.get(key) for key in identity)):
        raise ValueError("Prospective reports must share the same sport, model and cutoff")
    all_future = all_forecasts["prospective"]
    picks_future = recommendations["prospective"]
    paired_games = all_future.get("paired_games", 0)
    decided_picks = picks_future.get("decided", 0)
    pick_games = picks_future.get("settled_games", 0)
    counts = {"paired_games": paired_games, "decided_recommendations": decided_picks,
              "recommendation_games": pick_games}
    targets = {"paired_games": MIN_PAIRED_GAMES,
               "decided_recommendations": MIN_DECIDED_RECOMMENDATIONS,
               "recommendation_games": MIN_RECOMMENDATION_GAMES}
    result = {"status": "insufficient_data", "counts": counts, "minimum_counts": targets,
              "scope": "prospective hypothetical priced results; no executed bets recorded"}
    if any(counts[key] < target for key, target in targets.items()):
        return result
    market_interval = all_future.get("game_cluster_bootstrap_95")
    roi_interval = picks_future.get("ledger_performance", {}).get("roi_game_cluster_interval")
    if (not isinstance(market_interval, (list, tuple)) or len(market_interval) != 2
            or not isinstance(roi_interval, (list, tuple)) or len(roi_interval) != 2
            or any(value is None for value in (*market_interval, *roi_interval))):
        result["status"] = "uncertainty_unavailable"
        return result
    result["market_brier_difference_interval"] = list(market_interval)
    result["recorded_stake_roi_interval"] = list(roi_interval)
    result["status"] = ("prospective_hypothetical_edge_evidence"
                        if market_interval[1] < 0 and roi_interval[0] > 0
                        else "edge_not_demonstrated")
    return result
