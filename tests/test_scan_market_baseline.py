from __future__ import annotations

import pytest

from sportsbet.ingestion.prop_odds import parse_event_quotes, prop_quote_record_sha256
from sportsbet.quant.market_baseline import paired_market_baseline


def quotes():
    event = dict(id="game-1", commence_time="2026-09-21T20:00:00Z",
                 bookmakers=[dict(key="book-a", markets=[dict(
                     key="player_receptions", last_update="2026-09-21T18:00:00Z",
                     outcomes=[
                         dict(name="Over", description="Player One", point=2.5, price=-110),
                         dict(name="Under", description="Player One", point=2.5, price=-110),
                     ])])])
    return parse_event_quotes(event, "nfl")


def test_paired_market_baseline_records_exact_source_backed_opposite():
    over, under = quotes()
    result = paired_market_baseline(over, [over, under])
    assert result["market_no_vig_probability"] == pytest.approx(.5)
    assert result["market_opposite_american_odds"] == -110
    assert result["market_opposite_quote_source_record_sha256"] == under.source_record_sha256


def test_paired_market_baseline_requires_one_exact_opposite():
    over, under = quotes()
    assert paired_market_baseline(over, [over]) == {}
    assert paired_market_baseline(over, [over, under, under]) == {}
    later = under.model_copy(update={"snapped_at":under.snapped_at.replace(minute=1)})
    later = later.model_copy(update={"source_record_sha256":prop_quote_record_sha256(later)})
    assert paired_market_baseline(over, [over, later]) == {}
