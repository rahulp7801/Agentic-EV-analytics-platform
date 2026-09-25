import copy
from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest

from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, prop_quote_record_sha256
from sportsbet.ledger import Ledger
from sportsbet.quant import multisport_edge as audit
from sportsbet.quant.vig import american_to_raw_prob

NOW = datetime(2026, 9, 25, 5, tzinfo=timezone.utc)


def forecast(sport, captured="2026-09-25T04:00:00+00:00", **changes):
    prop, market = ("points", "player_points") if sport == "nba" else ("rec_yds", "player_reception_yds")
    p = dict(game_id=sport + "-game", player="Player One", player_id="7", sport=sport,
        game_date="2026-09-25", game_start_time="2026-09-26T00:00:00+00:00",
        home_team="Boston Celtics" if sport == "nba" else "Clemson Tigers",
        away_team="Los Angeles Lakers" if sport == "nba" else "Miami Hurricanes",
        prop_type=prop, direction="over", line=20.5, sportsbook="book", american_odds=-110,
        model_probability=.6, push_probability=0, model_version=audit.PROTOCOL["model_version"],
        recommendation_policy_version="confidence-floor-v2", accepted=True, stake_fraction=.01,
        captured_at=captured, quote_time=captured, model_generated_at=captured,
        quote_source_provider="the_odds_api", quote_source_sha256="a"*64)
    p.update(changes)
    quote=PlayerPropSnapshotCreate(sport=sport,game_id=p["game_id"],player_name=p["player"],
        sportsbook=p["sportsbook"],prop_type=market,line=Decimal(str(p["line"])),
        price=p["american_odds"],implied_probability=american_to_raw_prob(p["american_odds"]),
        game_start_time=datetime.fromisoformat(p["game_start_time"]),
        snapped_at=datetime.fromisoformat(p["quote_time"]),side=p["direction"].title(),
        source_provider=p["quote_source_provider"],source_sha256=p["quote_source_sha256"])
    p["quote_source_record_sha256"]=prop_quote_record_sha256(quote)
    return p


@pytest.mark.parametrize("sport", ["nba", "cfb"])
def test_exact_cutoff_separate_sports_and_pending_results(tmp_path, sport):
    ledger=Ledger(tmp_path/"ledger.sqlite")
    ledger.record("old",forecast(sport,"2026-09-25T03:59:59+00:00",recommendation_policy_version="old"))
    ledger.record("old-only",forecast(sport,"2026-09-25T03:59:59+00:00",game_id=sport+"-old-only"))
    ledger.record("at",forecast(sport))
    ledger.record("later",forecast(sport,"2026-09-25T04:01:00+00:00"))
    ledger.record("other",forecast("cfb" if sport=="nba" else "nba"))
    before=copy.deepcopy(ledger.predictions())
    result=audit.audit_sport(ledger,sport,now=NOW)
    assert result["status"]=="insufficient_data" and result["promote"] is False
    for report in result["cohorts"].values():
        assert report["earliest_selections"]==1 and report["pending"]==1
        assert report["decided"]==0
    assert result["assessment"]["counts"]["decided_recommendations"]==0
    assert ledger.predictions()==before
    assert "Player One" not in json.dumps(result)
    assert set(result["cohorts"])=={"all_predictions","recommendations"}


def test_empty_before_start_is_not_performance(tmp_path):
    ledger=Ledger(tmp_path/"ledger.sqlite")
    result=audit.audit_sport(ledger,"cfb",now=datetime(2026,9,25,3,tzinfo=timezone.utc))
    assert result["status"]=="awaiting_start"
    assert result["assessment"]["status"]=="insufficient_data"
    assert result["cohorts"]["recommendations"]["earliest_selections"]==0


@pytest.mark.parametrize("policy", [None,"new-policy",""])
def test_changed_or_missing_policy_stops_cohort(tmp_path, policy):
    ledger=Ledger(tmp_path/"ledger.sqlite")
    ledger.record("at",forecast("cfb",recommendation_policy_version=policy))
    with pytest.raises(ValueError,match="policy"):
        audit.audit_sport(ledger,"cfb",now=NOW)


def test_future_capture_is_not_counted_as_observed(tmp_path):
    ledger=Ledger(tmp_path/"ledger.sqlite")
    ledger.record("future",forecast("nba","2026-09-25T06:00:00+00:00"))
    with pytest.raises(ValueError,match="future"):
        audit.audit_sport(ledger,"nba",now=NOW)


def test_unverified_manual_outcome_stays_pending(tmp_path):
    ledger=Ledger(tmp_path/"ledger.sqlite")
    key=ledger.record("at",forecast("cfb"));ledger.settle({key:True})
    result=audit.audit_sport(ledger,"cfb",now=NOW)
    assert result["cohorts"]["recommendations"]["pending"]==1
    assert result["cohorts"]["recommendations"]["decided"]==0


def test_rejections_do_not_enter_accepted_cohort(tmp_path):
    ledger=Ledger(tmp_path/"ledger.sqlite")
    ledger.record("at",forecast("nba",accepted=False,stake_fraction=0))
    result=audit.audit_sport(ledger,"nba",now=NOW)
    assert result["cohorts"]["all_predictions"]["earliest_selections"]==1
    assert result["cohorts"]["recommendations"]["earliest_selections"]==0


def test_tampered_source_cannot_enter_either_cohort(tmp_path):
    ledger=Ledger(tmp_path/"ledger.sqlite")
    p=forecast("cfb");p["quote_source_record_sha256"]="f"*64
    with ledger.connect() as db:
        db.execute("INSERT INTO predictions(id,scan_id,payload,outcome) VALUES (?,?,?,?)",
            ("tampered","at",json.dumps(p),None))
    result=audit.audit_sport(ledger,"cfb",now=NOW)
    assert all(r["earliest_selections"]==0 for r in result["cohorts"].values())


@pytest.mark.parametrize("sport", ["nfl","all","mlb"])
def test_other_sports_and_pooling_are_rejected(sport):
    with pytest.raises(ValueError,match="separately"):
        audit.audit_sport(None,sport,now=NOW)


def test_threshold_change_requires_new_protocol(tmp_path,monkeypatch):
    monkeypatch.setattr(audit.edge_evidence,"MIN_PAIRED_GAMES",49)
    with pytest.raises(ValueError,match="thresholds"):
        audit.audit_sport(Ledger(tmp_path/"ledger.sqlite"),"nba",now=NOW)
