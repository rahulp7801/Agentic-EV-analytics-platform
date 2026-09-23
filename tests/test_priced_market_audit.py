from __future__ import annotations

import pytest

from sportsbet.quant import priced_market_audit as audit


def row(*, prediction_id, direction, odds, captured, quote, sportsbook="book-a", line=2.5,
        outcome=True, probability=.7, game_id="game-1"):
    return dict(prediction_id=prediction_id, game_id=game_id, player="Player One",
                prop_type="receptions", direction=direction, line=line,
                sportsbook=sportsbook, american_odds=odds,
                quote_time=quote, captured_at=captured, model_probability=probability,
                outcome=outcome)


def test_exact_quote_pair_and_earliest_selection(monkeypatch):
    monkeypatch.setattr(audit, "_settled_outcome", lambda value: value["outcome"])
    rows = [
        row(prediction_id="early-over", direction="over", odds=-110,
            captured="2026-09-20T10:00:00+00:00", quote="2026-09-20T09:59:00+00:00"),
        row(prediction_id="matching-under", direction="under", odds=-110,
            captured="2026-09-20T10:00:01+00:00", quote="2026-09-20T09:59:00+00:00",
            outcome=False, probability=.3),
        row(prediction_id="later-over", direction="over", odds=150,
            captured="2026-09-20T11:00:00+00:00", quote="2026-09-20T10:59:00+00:00"),
        row(prediction_id="other-book", direction="under", odds=-200,
            captured="2026-09-20T10:00:02+00:00", quote="2026-09-20T09:59:00+00:00",
            sportsbook="book-b", outcome=False),
    ]
    result = audit.compare_eligible_rows(rows, bootstrap_samples=0)
    assert result["source_eligible"] == 4
    assert result["earliest_selections"] == 2
    assert result["decided"] == 2
    assert result["paired_decided"] == 2
    assert result["paired_market_no_vig_brier"] == pytest.approx(.25)
    assert result["paired_model_brier"] == pytest.approx(.09)
    assert result["hypothetical_flat_stake_roi"] == pytest.approx((100/110-1)/2)


def test_opposite_quote_requires_exact_timestamp(monkeypatch):
    monkeypatch.setattr(audit, "_settled_outcome", lambda value: value["outcome"])
    rows = [
        row(prediction_id="over", direction="over", odds=-110,
            captured="2026-09-20T10:00:00+00:00", quote="2026-09-20T09:59:00+00:00"),
        row(prediction_id="under", direction="under", odds=-110,
            captured="2026-09-20T10:00:01+00:00", quote="2026-09-20T09:59:01+00:00",
            outcome=False),
    ]
    result = audit.compare_eligible_rows(rows, bootstrap_samples=0)
    assert result["decided"] == 2
    assert result["paired_decided"] == 0
    assert result["paired_market_no_vig_brier"] is None


def test_leave_one_game_out_blend_scores_unseen_games(monkeypatch):
    monkeypatch.setattr(audit, "_settled_outcome", lambda value: value["outcome"])
    rows = []
    for game_id, over_won in (("good-game", True), ("bad-game", False)):
        rows.extend([
            row(prediction_id=game_id+"-over", game_id=game_id, direction="over",
                odds=-110, captured="2026-09-20T10:00:00+00:00",
                quote="2026-09-20T09:59:00+00:00", outcome=over_won,
                probability=.7),
            row(prediction_id=game_id+"-under", game_id=game_id, direction="under",
                odds=-110, captured="2026-09-20T10:00:01+00:00",
                quote="2026-09-20T09:59:00+00:00", outcome=not over_won,
                probability=.3),
        ])
    result = audit.compare_eligible_rows(rows, bootstrap_samples=0)
    assert result["paired_market_no_vig_brier"] == pytest.approx(.25)
    assert result["market_model_leave_one_game_out_brier"] == pytest.approx(.37)
    assert result["leave_one_game_out_weight_range"] == pytest.approx([0, 1])
    assert result["leave_one_game_out_positive_weights"] == 1
