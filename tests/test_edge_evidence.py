import pytest

from sportsbet.quant.edge_evidence import assess_prospective_edge


def reports(*, paired_games=0, decided=0, pick_games=0,
            market_interval=None, roi_interval=None):
    shared = dict(sport="nfl", model_version="empirical-jeffreys-v4",
                  captured_after="2026-09-23T00:34:15+00:00")
    all_forecasts = dict(**shared, cohort="all_predictions",
                         prospective=dict(paired_games=paired_games,
                                          game_cluster_bootstrap_95=market_interval))
    picks = dict(**shared, cohort="recommendations",
                 prospective=dict(decided=decided, settled_games=pick_games,
                                  ledger_performance=dict(roi_game_cluster_interval=roi_interval)))
    return all_forecasts, picks


def test_edge_gate_waits_for_independent_games_and_picks():
    all_forecasts, picks = reports(paired_games=49, decided=100, pick_games=30,
                                  market_interval=[-.04, -.01], roi_interval=[.01, .2])
    result = assess_prospective_edge(all_forecasts, picks)
    assert result["status"] == "insufficient_data"
    assert result["minimum_counts"]["paired_games"] == 50


def test_edge_gate_requires_both_market_and_return_intervals():
    all_forecasts, picks = reports(paired_games=50, decided=100, pick_games=30,
                                  market_interval=[-.04, -.01], roi_interval=[.01, .2])
    assert assess_prospective_edge(all_forecasts, picks)["status"] == "prospective_hypothetical_edge_evidence"
    picks["prospective"]["ledger_performance"]["roi_game_cluster_interval"] = [-.02, .2]
    assert assess_prospective_edge(all_forecasts, picks)["status"] == "edge_not_demonstrated"
    picks["prospective"]["ledger_performance"]["roi_game_cluster_interval"] = None
    assert assess_prospective_edge(all_forecasts, picks)["status"] == "uncertainty_unavailable"


def test_edge_gate_rejects_mismatched_cohorts():
    all_forecasts, picks = reports()
    picks["model_version"] = "different"
    with pytest.raises(ValueError):
        assess_prospective_edge(all_forecasts, picks)
