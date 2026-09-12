"""Tests for Context Agent NBA routing and vig_method dispatch (Phase 15).

Covers three requirements:
  CTXT-01: Context Agent populates odds_snapshot for NBA routes (via fetch_nba_odds)
  CTXT-04: NBA sport routing — state["sport"]="nba" routes to fetch_nba_odds(), not fetch_nfl_odds()
  QUANT-02: Pinnacle power devig is config-selectable; vig_method="pinnacle" dispatches to remove_vig_power

All Odds API HTTP calls are mocked. No live API credits consumed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.graph.agents import _extract_odds_snapshot, make_context_agent
from sportsbet.ingestion.odds_poller import OddsAPIPoller
from sportsbet.ingestion.scraper import InjuryWeatherScraper

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

NBA_ODDS_FIXTURE = [
    {
        "id": "nba_game_001",
        "home_team": "Boston Celtics",
        "commence_time": "2026-12-01T20:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "last_update": datetime.now(timezone.utc).isoformat(),
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Celtics", "price": -200},
                            {"name": "Miami Heat", "price": 170},
                        ],
                    }
                ],
            }
        ],
    }
]

# Same asymmetric -200/+170 odds used for vig_method dispatch tests
ASYMMETRIC_ODDS_FIXTURE = NBA_ODDS_FIXTURE


def test_quote_identity_and_observation_time_do_not_depend_on_list_order():
    from copy import deepcopy
    event = deepcopy(NBA_ODDS_FIXTURE[0])
    event['bookmakers'][0]['last_update'] = '2026-01-01T12:00:00Z'
    unrelated = {**deepcopy(event), 'id':'unrelated'}
    snap = _extract_odds_snapshot([unrelated,event], 'nba_game_001', outcome_name='Miami Heat')
    assert snap is not None
    assert snap.game_id == 'nba_game_001'
    assert snap.outcome_name == 'Miami Heat'
    assert snap.american_odds == 170
    assert snap.snapped_at == datetime(2026,1,1,12,tzinfo=timezone.utc)
    assert _extract_odds_snapshot([unrelated], 'nba_game_001') is None
    assert _extract_odds_snapshot([event,event], 'nba_game_001') is None
    assert _extract_odds_snapshot([event], 'nba_game_001', outcome_name='Unknown') is None
    del event['bookmakers'][0]['last_update']
    assert _extract_odds_snapshot([event], 'nba_game_001') is None


def _make_full_state(sport: str | None = None) -> dict:
    """Return a complete GraphState-compatible dict for make_context_agent tests.

    sport=None exercises the default NFL routing path.
    sport="nba" exercises the Phase 15 NBA routing path.
    """
    state: dict = {
        "session_id": "test-session-001",
        "request_type": "context_update",
        "created_at": datetime.now(timezone.utc),
        "game_id": "nba_game_001",
        "season": 2025,
        "week": 1,
        "home_team": "BOS",
        "away_team": "MIA",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "context_signals": None,
        "pending_signals": [],
        "cleared_signals": [],
        "kinematic_result": None,
        "receiver_gsis_id": "",
        "prop_result": None,
        "nba_context_signals": None,
        "nba_prop_result": None,
        "prop_type": "points",
        "prop_line": "22.5",
        "prop_filters": None,
    }
    if sport is not None:
        state["sport"] = sport
    return state


# ---------------------------------------------------------------------------
# CTXT-04: NBA routing — fetch_nba_odds called when state["sport"]="nba"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nba_context_agent_fetches_nba_odds() -> None:
    """make_context_agent with state["sport"]="nba" calls fetch_nba_odds (not fetch_nfl_odds).

    Verifies:
    1. fetch_nba_odds is called exactly once
    2. fetch_nfl_odds is NOT called
    3. result["context_signals"].odds_snapshot is not None (fixture has valid h2h market)
    """
    mock_pool = MagicMock()
    state = _make_full_state(sport="nba")

    with (
        patch.object(OddsAPIPoller, "fetch_nba_odds", new_callable=AsyncMock, return_value=NBA_ODDS_FIXTURE) as mock_nba,
        patch.object(OddsAPIPoller, "fetch_nfl_odds", new_callable=AsyncMock, return_value=[]) as mock_nfl,
        patch.object(OddsAPIPoller, "fetch_player_props", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.graph.agents.write_player_prop_snapshot"),
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports", new_callable=AsyncMock, return_value=0),
    ):
        agent = make_context_agent(mock_pool, api_key="test-key", daily_credit_cap=500)
        result = await agent(state)  # type: ignore[arg-type]

    mock_nba.assert_called_once()
    mock_nfl.assert_not_called()
    assert result["context_signals"] is not None
    assert result["context_signals"].odds_snapshot is not None


# ---------------------------------------------------------------------------
# CTXT-04 regression: NFL default path unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nfl_default_still_calls_fetch_nfl_odds() -> None:
    """make_context_agent with no sport field still calls fetch_nfl_odds — regression guard.

    Existing NFL tests pass state without a "sport" key. The agent must default to
    "nfl" routing via state.get("sport") or "nfl" and call fetch_nfl_odds, not
    fetch_nba_odds.
    """
    mock_pool = MagicMock()
    # _make_full_state(sport=None) does NOT include a "sport" key in the dict
    state = _make_full_state(sport=None)
    # Ensure "sport" key is absent (tests default path)
    state.pop("sport", None)

    nfl_fixture = [
        {
            "id": "nfl_game_001",
            "bookmakers": [
                {
                    "key": "draftkings",
                "last_update": datetime.now(timezone.utc).isoformat(),
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Kansas City Chiefs", "price": -180},
                                {"name": "Los Angeles Chargers", "price": 155},
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    with (
        patch.object(OddsAPIPoller, "fetch_nfl_odds", new_callable=AsyncMock, return_value=nfl_fixture) as mock_nfl,
        patch.object(OddsAPIPoller, "fetch_nba_odds", new_callable=AsyncMock, return_value=[]) as mock_nba,
        patch.object(OddsAPIPoller, "fetch_player_props", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.graph.agents.write_player_prop_snapshot"),
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports", new_callable=AsyncMock, return_value=0),
    ):
        agent = make_context_agent(mock_pool, api_key="test-key", daily_credit_cap=500)
        result = await agent(state)  # type: ignore[arg-type]

    mock_nfl.assert_called_once()
    mock_nba.assert_not_called()


# ---------------------------------------------------------------------------
# QUANT-02: vig_method dispatch — pinnacle vs multiplicative differ on asymmetric market
# ---------------------------------------------------------------------------


def test_pinnacle_devig_differs_from_multiplicative() -> None:
    """_extract_odds_snapshot with vig_method="pinnacle" returns different implied_probability than "multiplicative".

    Uses -200/+170 asymmetric fixture. Power (Pinnacle) devig corrects for
    favorite-longshot bias, shifting more probability to the favorite (-200).
    Therefore: power result implied_probability > multiplicative result implied_probability.
    """
    snap_mult = _extract_odds_snapshot(ASYMMETRIC_ODDS_FIXTURE, "nba_game_001", vig_method="multiplicative")
    snap_power = _extract_odds_snapshot(ASYMMETRIC_ODDS_FIXTURE, "nba_game_001", vig_method="pinnacle")

    assert snap_mult is not None, "multiplicative snapshot should not be None"
    assert snap_power is not None, "pinnacle snapshot should not be None"
    assert snap_mult.implied_probability != snap_power.implied_probability, (
        "pinnacle and multiplicative should produce different fair probabilities "
        f"for asymmetric -200/+170 market; got mult={snap_mult.implied_probability}, "
        f"power={snap_power.implied_probability}"
    )
    # Power devig shifts weight to the favorite — implied_probability of first outcome (-200) should be higher
    assert snap_power.implied_probability > snap_mult.implied_probability, (
        f"power devig should assign higher probability to favorite; "
        f"power={snap_power.implied_probability}, mult={snap_mult.implied_probability}"
    )


# ---------------------------------------------------------------------------
# QUANT-02: multiplicative (default) matches remove_vig_multiplicative directly
# ---------------------------------------------------------------------------


def test_vig_method_multiplicative_uses_remove_vig_multiplicative() -> None:
    """vig_method="multiplicative" (default) produces the same result as remove_vig_multiplicative directly.

    This is the backward-compatibility test: existing behavior must be preserved
    when no vig_method is provided (defaults to "multiplicative").
    """
    from sportsbet.quant.vig import american_to_raw_prob, remove_vig_multiplicative

    snap = _extract_odds_snapshot(ASYMMETRIC_ODDS_FIXTURE, "nba_game_001", vig_method="multiplicative")
    assert snap is not None

    # Compute expected fair_prob directly
    raw_probs = [american_to_raw_prob(-200), american_to_raw_prob(170)]
    fair_probs = remove_vig_multiplicative(raw_probs)
    from decimal import ROUND_HALF_EVEN
    expected_prob = fair_probs[0].quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_EVEN)

    assert snap.implied_probability == expected_prob, (
        f"multiplicative vig_method should match remove_vig_multiplicative directly; "
        f"got {snap.implied_probability}, expected {expected_prob}"
    )


# ---------------------------------------------------------------------------
# QUANT-02: make_context_agent reads vig_method param and passes to _extract_odds_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_context_agent_reads_vig_method_from_settings() -> None:
    """make_context_agent(pool, api_key, daily_credit_cap, vig_method="pinnacle") passes "pinnacle" into _extract_odds_snapshot.

    Uses a spy/mock on _extract_odds_snapshot to confirm vig_method is forwarded
    from the make_context_agent construction parameter into each snapshot extraction call.
    """
    mock_pool = MagicMock()
    state = _make_full_state(sport="nba")

    with (
        patch.object(OddsAPIPoller, "fetch_nba_odds", new_callable=AsyncMock, return_value=NBA_ODDS_FIXTURE),
        patch.object(OddsAPIPoller, "fetch_player_props", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.graph.agents.write_player_prop_snapshot"),
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports", new_callable=AsyncMock, return_value=0),
        patch("sportsbet.graph.agents._extract_odds_snapshot", wraps=_extract_odds_snapshot) as mock_extract,
    ):
        agent = make_context_agent(mock_pool, api_key="test-key", daily_credit_cap=500, vig_method="pinnacle")
        await agent(state)  # type: ignore[arg-type]

    # Confirm _extract_odds_snapshot was called with vig_method="pinnacle"
    assert mock_extract.called, "_extract_odds_snapshot should have been called"
    call_kwargs = mock_extract.call_args
    # Check either positional or keyword argument
    args, kwargs = call_kwargs
    vig_passed = kwargs.get("vig_method") or (args[2] if len(args) > 2 else None)
    assert vig_passed == "pinnacle", (
        f"_extract_odds_snapshot should receive vig_method='pinnacle'; got {vig_passed!r}"
    )


# ---------------------------------------------------------------------------
# GAP-INT-1: fetch_player_props called with dynamic sport variable (not "nfl")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_player_props_called_with_nba_when_sport_is_nba() -> None:
    """make_context_agent with state["sport"]="nba" calls fetch_player_props("nba"), not fetch_player_props("nfl").

    Verifies GAP-INT-1 fix: the sport variable (state.get("sport") or "nfl")
    is passed into fetch_player_props instead of the hardcoded literal "nfl".
    """
    from unittest.mock import call

    mock_pool = MagicMock()
    state = _make_full_state(sport="nba")

    with (
        patch.object(OddsAPIPoller, "fetch_nba_odds", new_callable=AsyncMock, return_value=NBA_ODDS_FIXTURE),
        patch.object(OddsAPIPoller, "fetch_nfl_odds", new_callable=AsyncMock, return_value=[]),
        patch.object(OddsAPIPoller, "fetch_player_props", new_callable=AsyncMock, return_value=[]) as mock_props,
        patch("sportsbet.graph.agents.write_player_prop_snapshot"),
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports", new_callable=AsyncMock, return_value=0),
    ):
        agent = make_context_agent(mock_pool, api_key="test-key", daily_credit_cap=500)
        await agent(state)  # type: ignore[arg-type]

    mock_props.assert_called_once_with("nba")


@pytest.mark.asyncio
async def test_fetch_player_props_called_with_nfl_when_sport_absent() -> None:
    """make_context_agent with no sport key calls fetch_player_props("nfl") — regression guard.

    Verifies the default NFL path is not broken by the GAP-INT-1 fix.
    """
    mock_pool = MagicMock()
    state = _make_full_state(sport=None)
    state.pop("sport", None)

    with (
        patch.object(OddsAPIPoller, "fetch_nfl_odds", new_callable=AsyncMock, return_value=[]),
        patch.object(OddsAPIPoller, "fetch_nba_odds", new_callable=AsyncMock, return_value=[]),
        patch.object(OddsAPIPoller, "fetch_player_props", new_callable=AsyncMock, return_value=[]) as mock_props,
        patch("sportsbet.graph.agents.write_player_prop_snapshot"),
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports", new_callable=AsyncMock, return_value=0),
    ):
        agent = make_context_agent(mock_pool, api_key="test-key", daily_credit_cap=500)
        await agent(state)  # type: ignore[arg-type]

    mock_props.assert_called_once_with("nfl")


@pytest.mark.asyncio
async def test_unavailable_priced_props_fail_closed_without_public_projection_fallbacks() -> None:
    """A sportsbook outage must not turn unpriced projections into quote evidence."""
    mock_pool=MagicMock();state=_make_full_state(sport="nba")
    with (
        patch.object(OddsAPIPoller,"fetch_nba_odds",new_callable=AsyncMock,return_value=[]),
        patch.object(OddsAPIPoller,"fetch_player_props",new_callable=AsyncMock,
            side_effect=RuntimeError("private provider detail")) as mock_props,
        patch("sportsbet.graph.agents.write_player_prop_snapshot") as write_prop,
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sqlalchemy.create_engine",return_value=MagicMock()) as create_engine,
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries",
            new_callable=AsyncMock,return_value=[]),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports",
            new_callable=AsyncMock,return_value=0),
    ):
        result=await make_context_agent(mock_pool,api_key="test-key",daily_credit_cap=500)(state)
    mock_props.assert_called_once_with("nba")
    write_prop.assert_not_called()
    create_engine.assert_not_called()
    assert result["player_prop_snapshots"] is None


@pytest.mark.asyncio
async def test_unavailable_h2h_odds_fail_closed_without_unverified_fallbacks() -> None:
    """A sportsbook outage must leave h2h evidence absent."""
    mock_pool=MagicMock();state=_make_full_state(sport="nba")
    with (
        patch.object(OddsAPIPoller,"fetch_nba_odds",new_callable=AsyncMock,
            side_effect=RuntimeError("private provider detail")),
        patch.object(OddsAPIPoller,"fetch_player_props",new_callable=AsyncMock,return_value=[]),
        patch("sportsbet.graph.agents.write_player_prop_snapshot"),
        patch("sportsbet.graph.agents.write_odds_snapshot") as write_odds,
        patch("sqlalchemy.create_engine",return_value=MagicMock()) as create_engine,
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries",
            new_callable=AsyncMock,return_value=[]),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports",
            new_callable=AsyncMock,return_value=0),
    ):
        result=await make_context_agent(mock_pool,api_key="test-key",daily_credit_cap=500)(state)
    write_odds.assert_not_called()
    create_engine.assert_not_called()
    assert result["context_signals"].odds_snapshot is None


@pytest.fixture(autouse=True)
def isolated_injury_sources(monkeypatch):
    # These tests exercise orchestration with fixture data, never live injury feeds.
    monkeypatch.setattr('sportsbet.graph.agents._fetch_sleeper_injuries', AsyncMock(return_value=[]))
