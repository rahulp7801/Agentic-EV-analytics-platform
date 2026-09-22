"""Regression checks for the retrospective reception offer audit."""
from __future__ import annotations

import pytest

from sportsbet.quant.reception_offer_audit import audit


START = "2026-09-15T00:15:00+00:00"
CAPTURE = "2026-09-14T20:59:33+00:00"


def replay_row(name: str = "Jaylen Waddle", probability: float = 0.390625,
               actual: int = 1, event: str = "espn-1") -> dict:
    return {
        "id": f"{event}-{name}", "event_id": event, "player_name": name,
        "prop_type": "receptions", "research_threshold": 4.5,
        "model_probability": probability, "actual_value": actual,
        "outcome": actual > 4.5, "game_start_time": START,
    }


def quote(quote_id: int, side: str, price: int, line: float = 4.5,
          player: str = "Jaylen Waddle", event: str = "odds-1",
          captured: str = CAPTURE) -> dict:
    return {
        "id": quote_id, "sport": "nfl", "game_id": event,
        "player_name": player, "sportsbook": "bovada",
        "prop_type": "player_receptions", "line": line,
        "price": price, "side": side, "game_start_time": START,
        "snapped_at": captured, "source_provider": "the_odds_api",
        "source_sha256": "a" * 64, "source_record_sha256": "b" * 64,
    }


def one_replay(*rows: dict) -> list[dict]:
    return [{"id": "week-one", "records": list(rows)}]


def test_candidate_offer_keeps_market_comparison_and_profit_unavailable() -> None:
    report = audit(one_replay(replay_row()), [quote(1, "Over", -135), quote(2, "Under", 105)])
    assert report["total"] == {
        "evaluated": 1, "selected": 1, "model_correct": 1,
        "always_under_correct": 1, "candidate_exact_offers": 1,
        "all_evaluated_candidate_exact_offers": 1,
        "selected_offer_statuses": {"candidate_exact_offer": 1},
        "valid_quote_rows": 2, "rejected_quote_rows": 0,
    }
    row = report["rows"][0]
    assert row["offer_status"] == "candidate_exact_offer"
    assert [offer["id"] for offer in row["observed_offers"]] == [1, 2]
    assert row["market_comparison"]["candidate_entry"]["id"] == 2
    assert row["market_comparison"]["model_side_probability"] == 0.609375
    assert row["market_comparison"]["raw_break_even_probability"] == pytest.approx(100 / 205)
    assert row["market_comparison"]["market_no_vig_probability"] == pytest.approx(
        (100 / 205) / (100 / 205 + 135 / 235)
    )
    assert row["market_comparison"]["illustrative_expected_net_per_unit"] == pytest.approx(0.24921875)
    assert row["market_comparison"]["illustrative_model_profit_per_unit"] == pytest.approx(1.05)
    assert row["market_comparison"]["illustrative_always_under_profit_per_unit"] == pytest.approx(1.05)
    assert report["priced_strategy"]["roi"] is None
    assert report["priced_strategy"]["clv"] is None


def test_rejections_preserve_all_selected_rows_in_denominator() -> None:
    rows = [replay_row("Alternate", 0.2, 2), replay_row("Missing", 0.2, 1)]
    offers = [quote(1, "Under", -105, line=2.5, player="Alternate")]
    report = audit(one_replay(*rows), offers)
    assert report["total"]["selected"] == 2
    assert report["total"]["candidate_exact_offers"] == 0
    assert report["total"]["selected_offer_statuses"] == {
        "different_line": 1, "no_player_quotes": 1,
    }
    assert report["rows"][0]["observed_offers"][0]["line"] == "2.5"


def test_postgame_and_ambiguous_quotes_fail_closed() -> None:
    postgame = quote(1, "Under", 105, captured="2026-09-15T00:16:00+00:00")
    report = audit(one_replay(replay_row()), [postgame])
    assert report["total"]["rejected_quote_rows"] == 1
    assert report["rows"][0]["offer_status"] == "no_event_quotes"
    assert report["priced_strategy"]["roi"] is None

    report = audit(one_replay(replay_row()), [
        quote(1, "Under", 105), quote(2, "Under", 105, event="odds-2")
    ])
    assert report["rows"][0]["offer_status"] == "ambiguous_provider_event"
    assert report["total"]["candidate_exact_offers"] == 0


def test_replay_outcome_and_identity_must_be_consistent() -> None:
    row = replay_row()
    row["outcome"] = True
    with pytest.raises(ValueError, match="outcome disagrees"):
        audit(one_replay(row), [])
    row = replay_row()
    with pytest.raises(ValueError, match="duplicate replay ID"):
        audit(one_replay(row, row), [])
