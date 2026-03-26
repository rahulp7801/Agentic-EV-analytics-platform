"""Phase 19 integration regression tests (19-01-PLAN.md).

Covers two integration gaps identified in the v1.0 milestone audit:

  INT-2 — NBA prop snapshots written with sport='nfl' hardcoded (agents.py line 304).
           PlayerPropSnapshotCreate must use the sport variable, not a literal.

  INT-1 — make_prop_quant_agent and make_nba_quant_agent never read
           situational_params from GraphState, so teammate_out conditional WHERE
           clauses in Phase 18 never fire in automated pipeline runs.

TDD: tests 1, 3, 4 written RED before source fixes.
     tests 2, 5 are regression guards — already green before any changes.
After Task 2 applies the three source-file fixes, all 5 tests must turn GREEN.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.graph.models import PropResult


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

def _minimal_state(**overrides: Any) -> dict[str, Any]:
    """Return a minimal GraphState-compatible dict for prop agent tests."""
    base: dict[str, Any] = {
        "session_id": "s1",
        "game_id": "g1",
        "season": 2023,
        "receiver_gsis_id": "00-0036355",
        "prop_type": "rec_yds",
        "prop_line": 75.5,
        "prop_filters": {},
    }
    base.update(overrides)
    return base


def _fake_prop_result() -> PropResult:
    return PropResult(
        data_source="test",
        true_probability=Decimal("0.6"),
        sample_size=35,
        confidence_interval=(Decimal("0.5"), Decimal("0.7")),
    )


def _context_agent_state(sport: str | None = None) -> dict[str, Any]:
    """Return minimal GraphState for context_agent tests."""
    state: dict[str, Any] = {
        "session_id": str(uuid.uuid4()),
        "request_type": "context_update",
        "created_at": datetime.now(timezone.utc),
        "game_id": "2024_01_KC_LV",
        "season": 2024,
        "week": 1,
        "home_team": "KC",
        "away_team": "LV",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "context_signals": None,
        "pending_signals": [],
        "cleared_signals": [],
        "receiver_gsis_id": "",
        "prop_result": None,
        "nba_context_signals": None,
        "nba_prop_result": None,
        "prop_type": "points",
        "prop_line": "25.5",
        "prop_filters": None,
    }
    if sport is not None:
        state["sport"] = sport
    return state


def _raw_props_fixture(game_id: str = "test-game-123") -> list[dict]:
    return [
        {
            "id": game_id,
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {
                                    "name": "LeBron James",
                                    "price": -110,
                                    "point": 25.5,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]


# ---------------------------------------------------------------------------
# Test 1: INT-2 — snapshot sport variable for NBA state (currently RED — sport hardcoded to 'nfl')
# ---------------------------------------------------------------------------

def test_prop_snapshot_uses_sport_variable_nba() -> None:
    """INT-2: When state['sport']='nba', PlayerPropSnapshotCreate must be called
    with sport='nba', not the hardcoded 'nfl' literal.

    This test fails BEFORE the fix because line 304 of agents.py passes
    sport='nfl' as a literal string.
    """
    from sportsbet.graph.agents import make_context_agent

    raw_props = _raw_props_fixture()
    state = _context_agent_state(sport="nba")

    captured_snaps: list[Any] = []

    def capture_snap(snap: Any, engine: Any) -> None:
        captured_snaps.append(snap)

    mock_pool = MagicMock()

    with (
        patch("sportsbet.graph.agents.write_player_prop_snapshot", side_effect=capture_snap),
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.graph.agents.get_sync_engine"),
        patch("sportsbet.graph.agents.OddsAPIPoller") as mock_poller_cls,
        patch("sportsbet.graph.agents.InjuryWeatherScraper") as mock_scraper_cls,
        patch("sportsbet.graph.agents.httpx") as mock_httpx,
    ):
        mock_poller_instance = AsyncMock()
        mock_poller_instance.fetch_nba_odds = AsyncMock(return_value=[])
        mock_poller_instance.fetch_nfl_odds = AsyncMock(return_value=[])
        mock_poller_instance.fetch_player_props = AsyncMock(return_value=raw_props)
        mock_poller_cls.return_value.__aenter__ = AsyncMock(return_value=mock_poller_instance)
        mock_poller_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_scraper_instance = AsyncMock()
        mock_scraper_instance.fetch_team_injuries = AsyncMock(return_value=[])
        mock_scraper_instance.write_injury_reports = AsyncMock(return_value=None)
        mock_scraper_cls.return_value = mock_scraper_instance

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient.return_value = mock_client

        agent = make_context_agent(pool=mock_pool, api_key="test-key", daily_credit_cap=500)
        asyncio.run(agent(state))

    assert captured_snaps, "write_player_prop_snapshot was never called"
    assert captured_snaps[0].sport == "nba", (
        f"INT-2: Expected sport='nba' but got sport='{captured_snaps[0].sport}'. "
        "PlayerPropSnapshotCreate uses hardcoded 'nfl' literal — fix not yet applied."
    )


# ---------------------------------------------------------------------------
# Test 2: INT-2 regression guard — NFL default stays 'nfl' (currently GREEN)
# ---------------------------------------------------------------------------

def test_prop_snapshot_sport_defaults_to_nfl() -> None:
    """Regression guard: when state has no 'sport' key, sport defaults to 'nfl'.

    This test must remain GREEN before and after the INT-2 fix.
    """
    from sportsbet.graph.agents import make_context_agent

    raw_props = _raw_props_fixture()
    # No 'sport' key in state — should default to 'nfl'
    state = _context_agent_state(sport=None)

    captured_snaps: list[Any] = []

    def capture_snap(snap: Any, engine: Any) -> None:
        captured_snaps.append(snap)

    mock_pool = MagicMock()

    with (
        patch("sportsbet.graph.agents.write_player_prop_snapshot", side_effect=capture_snap),
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.graph.agents.get_sync_engine"),
        patch("sportsbet.graph.agents.OddsAPIPoller") as mock_poller_cls,
        patch("sportsbet.graph.agents.InjuryWeatherScraper") as mock_scraper_cls,
        patch("sportsbet.graph.agents.httpx") as mock_httpx,
    ):
        mock_poller_instance = AsyncMock()
        mock_poller_instance.fetch_nfl_odds = AsyncMock(return_value=[])
        mock_poller_instance.fetch_nba_odds = AsyncMock(return_value=[])
        mock_poller_instance.fetch_player_props = AsyncMock(return_value=raw_props)
        mock_poller_cls.return_value.__aenter__ = AsyncMock(return_value=mock_poller_instance)
        mock_poller_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_scraper_instance = AsyncMock()
        mock_scraper_instance.fetch_team_injuries = AsyncMock(return_value=[])
        mock_scraper_instance.write_injury_reports = AsyncMock(return_value=None)
        mock_scraper_cls.return_value = mock_scraper_instance

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient.return_value = mock_client

        agent = make_context_agent(pool=mock_pool, api_key="test-key", daily_credit_cap=500)
        asyncio.run(agent(state))

    assert captured_snaps, "write_player_prop_snapshot was never called"
    assert captured_snaps[0].sport == "nfl", (
        f"Regression: expected sport='nfl' default but got '{captured_snaps[0].sport}'"
    )


# ---------------------------------------------------------------------------
# Test 3: INT-1 NFL — prop_quant_agent forwards teammate_out (currently RED)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prop_quant_agent_forwards_teammate_out() -> None:
    """INT-1 NFL: make_prop_quant_agent must forward teammate_out_signals from
    situational_params to PropParams.teammate_out.

    Fails BEFORE the fix because prop_quant_agent never reads situational_params.
    """
    from sportsbet.prop.agents import make_prop_quant_agent

    captured_params: list[Any] = []

    async def fake_run_prop_query(pool: Any, params: Any) -> PropResult:
        captured_params.append(params)
        return _fake_prop_result()

    state = _minimal_state(
        situational_params={"teammate_out_signals": ["Davante Adams"]},
    )
    mock_pool = MagicMock()

    with patch("sportsbet.prop.agents.run_prop_query", side_effect=fake_run_prop_query):
        agent = make_prop_quant_agent(mock_pool)
        await agent(state)

    assert captured_params, "run_prop_query was never called"
    params = captured_params[0]
    assert params.teammate_out == ["Davante Adams"], (
        f"INT-1: Expected params.teammate_out=['Davante Adams'] but got {params.teammate_out!r}. "
        "Bridge from situational_params to PropParams not yet applied."
    )


# ---------------------------------------------------------------------------
# Test 4: INT-1 NBA — nba_quant_agent forwards teammate_out (currently RED)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nba_quant_agent_forwards_teammate_out() -> None:
    """INT-1 NBA: make_nba_quant_agent must forward teammate_out_signals from
    situational_params to PropParams.teammate_out.

    Fails BEFORE the fix because nba_quant_agent never reads situational_params.
    """
    from sportsbet.prop.nba_agents import make_nba_quant_agent

    captured_params: list[Any] = []

    async def fake_run_nba_prop_query(pool: Any, params: Any) -> PropResult:
        captured_params.append(params)
        return _fake_prop_result()

    state = _minimal_state(
        prop_type="points",
        situational_params={"teammate_out_signals": ["Anthony Davis"]},
    )
    mock_pool = MagicMock()

    with patch("sportsbet.prop.nba_agents.run_nba_prop_query", side_effect=fake_run_nba_prop_query):
        agent = make_nba_quant_agent(mock_pool)
        await agent(state)

    assert captured_params, "run_nba_prop_query was never called"
    params = captured_params[0]
    assert params.teammate_out == ["Anthony Davis"], (
        f"INT-1 NBA: Expected params.teammate_out=['Anthony Davis'] but got {params.teammate_out!r}. "
        "Bridge from situational_params to PropParams not yet applied."
    )


# ---------------------------------------------------------------------------
# Test 5: INT-1 backward compat — teammate_out is None when no situational_params
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prop_quant_agent_teammate_out_none_when_no_situational() -> None:
    """Backward compatibility guard: when state has no situational_params key,
    PropParams.teammate_out must be None (not an empty list or error).

    Must be GREEN before and after the INT-1 fix.
    """
    from sportsbet.prop.agents import make_prop_quant_agent

    captured_params: list[Any] = []

    async def fake_run_prop_query(pool: Any, params: Any) -> PropResult:
        captured_params.append(params)
        return _fake_prop_result()

    # No situational_params key in state
    state = _minimal_state()
    mock_pool = MagicMock()

    with patch("sportsbet.prop.agents.run_prop_query", side_effect=fake_run_prop_query):
        agent = make_prop_quant_agent(mock_pool)
        await agent(state)

    assert captured_params, "run_prop_query was never called"
    params = captured_params[0]
    assert params.teammate_out is None, (
        f"Backward compat: expected params.teammate_out is None but got {params.teammate_out!r}"
    )
