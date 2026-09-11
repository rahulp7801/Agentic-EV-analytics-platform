"""Phase 14 gap-closure integration tests (14-01-PLAN.md).

Tests confirm three wiring gaps identified in the v1.0 milestone audit:

  PROP-01  — context_agent calls write_player_prop_snapshot after fetching props
  PROP-06  — make_prop_arbitrage_agent(sport=None) auto-detects NBA state key
  INFRA-01 — GraphState TypedDict declares prop_filters field

TDD: all three tests written RED before any implementation code is changed.
After Task 2 applies the four source-file fixes, all tests must turn GREEN.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.graph.models import (
    AgentOddsSnapshot,
    ContextSignals,
    PropResult,
)


# ---------------------------------------------------------------------------
# Test 1: PROP-01 — context_agent persists player prop snapshots
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("requested_game, expected_count", [("2024_01_KC_LV", 1), ("unmatched-game", 0)])
def test_context_agent_calls_write_player_prop_snapshot(requested_game, expected_count) -> None:
    """Patch write_player_prop_snapshot at the agents module level.

    Confirms that make_context_agent, when OddsAPIPoller.fetch_player_props
    returns one event with one bookmaker/market/outcome containing price=-115,
    calls write_player_prop_snapshot at least once.

    Design: patches at sportsbet.graph.agents.* (module-level names) so that
    unittest.mock intercepts the actual call site used by the closure at runtime.
    """
    from sportsbet.graph.agents import make_context_agent

    # Minimal raw props event — one bookmaker, one market, one outcome
    raw_props_fixture = [
        {
            "id": "2024_01_KC_LV",
            "commence_time": "2024-09-08T17:00:00Z",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "last_update": "2024-09-08T16:00:00Z",
                    "markets": [
                        {
                            "key": "player_pass_yds",
                            "outcomes": [
                                {
                                    "name": "Over",
                                    "description": "Patrick Mahomes",
                                    "price": -115,
                                    "point": 275.5,
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    # Minimal raw odds response (needed for Step 1 / Step 1b to not error out)
    raw_odds_fixture: list = []

    # Build a minimal asyncpg pool mock (needed for make_context_agent constructor)
    mock_pool = MagicMock()

    initial_state = {
        "session_id": str(uuid.uuid4()),
        "request_type": "context_update",
        "created_at": datetime.now(timezone.utc),
        "game_id": requested_game,
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
        "prop_type": "pass_yds",
        "prop_line": "250.5",
        "prop_filters": None,
    }

    with (
        patch("sportsbet.graph.agents.write_player_prop_snapshot") as mock_write_snap,
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.graph.agents.get_sync_engine"),
        patch("sportsbet.graph.agents.OddsAPIPoller") as mock_poller_cls,
    ):
        # Configure OddsAPIPoller context manager for both fetch_nfl_odds
        # (Step 1) and fetch_player_props (Step 1c)
        mock_poller_instance = AsyncMock()
        mock_poller_instance.fetch_nfl_odds = AsyncMock(return_value=raw_odds_fixture)
        mock_poller_instance.fetch_player_props = AsyncMock(return_value=raw_props_fixture)
        # __aenter__ must return the mock instance so `async with ... as poller` works
        mock_poller_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_poller_instance
        )
        mock_poller_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # Also patch InjuryWeatherScraper to prevent real HTTP calls
        with patch("sportsbet.graph.agents.InjuryWeatherScraper") as mock_scraper_cls:
            mock_scraper_instance = AsyncMock()
            mock_scraper_instance.fetch_team_injuries = AsyncMock(return_value=[])
            mock_scraper_instance.write_injury_reports = AsyncMock(return_value=None)
            mock_scraper_cls.return_value = mock_scraper_instance

            # Also patch httpx.AsyncClient to avoid network
            with patch("sportsbet.graph.agents.httpx") as mock_httpx:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_httpx.AsyncClient.return_value = mock_client

                agent = make_context_agent(
                    pool=mock_pool,
                    api_key="test-key",
                    daily_credit_cap=500,
                )
                asyncio.run(agent(initial_state))

    assert mock_write_snap.call_count == expected_count
    if expected_count:
        snapshot = mock_write_snap.call_args.args[0]
        assert snapshot.snapped_at == datetime(2024, 9, 8, 16, tzinfo=timezone.utc)
        assert snapshot.game_start_time == datetime(2024, 9, 8, 17, tzinfo=timezone.utc)
        assert snapshot.side == 'Over'



# ---------------------------------------------------------------------------
# Test 2: PROP-06 — make_prop_arbitrage_agent(sport=None) resolves NBA key
# ---------------------------------------------------------------------------

def test_prop_arbitrage_sport_none_resolves_nba() -> None:
    """make_prop_arbitrage_agent(sport=None) must read nba_prop_result when present.

    Constructs a state with nba_prop_result set (true_probability=0.65) and
    prop_result=None. The agent must auto-detect the NBA key and return
    ev_signal is not None (given implied_probability=0.50 → +15% EV).
    """
    from sportsbet.prop.arbitrage import make_prop_arbitrage_agent

    nba_prop_result = PropResult(
        true_probability=Decimal("0.65"),
        sample_size=30,
        confidence_interval=(Decimal("0.55"), Decimal("0.75")),
        data_source="postgresql",
        mean_stat=Decimal("28.0"),
    )

    state = {
        "session_id": str(uuid.uuid4()),
        "request_type": "nba_prop_analysis",
        "created_at": datetime.now(timezone.utc),
        "game_id": "2024_01_BOS_MIA",
        "season": 2024,
        "week": 1,
        "home_team": "BOS",
        "away_team": "MIA",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "context_signals": ContextSignals(
            game_id="2024_01_BOS_MIA",
            injury_flags={},
            odds_snapshot=AgentOddsSnapshot(
                game_id="2024_01_BOS_MIA",
                sportsbook="draftkings",
                market_type="over_points",
                implied_probability=Decimal("0.50"),
                snapped_at=datetime.now(timezone.utc),
            ),
            signals_captured_at=datetime.now(timezone.utc),
        ),
        "prop_result": None,  # NFL prop is None
        "nba_prop_result": nba_prop_result,  # NBA prop is populated
        "pending_signals": [],
        "cleared_signals": [],
        "receiver_gsis_id": "",
        "kinematic_result": None,
        "prop_type": "points",
        "prop_line": "28.0",
        "nba_context_signals": None,
        "prop_filters": None,
    }

    from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
    state['player_name'] = 'Test Player'
    state['player_prop_snapshots'] = [PlayerPropSnapshotCreate(sport='nba',player_name='Test Player',
        sportsbook='draftkings',prop_type='player_points',side='Over',line=Decimal('28.0'),price=100,implied_probability=Decimal('.5'))]
    agent = make_prop_arbitrage_agent(sport=None)
    result = asyncio.run(agent(state))

    assert result.get("ev_signal") is not None, (
        "make_prop_arbitrage_agent(sport=None) returned ev_signal=None even though "
        "nba_prop_result has true_probability=0.65 and implied=0.50 (+15% EV). "
        "PROP-06 gap not yet closed."
    )


# ---------------------------------------------------------------------------
# Test 3: INFRA-01 — GraphState TypedDict declares prop_filters
# ---------------------------------------------------------------------------

def test_graphstate_declares_prop_filters() -> None:
    """GraphState.__annotations__ must include 'prop_filters'.

    This is a static structural check — no async runtime behavior involved.
    Fails until state.py adds prop_filters: dict[str, Any] | None to GraphState.
    """
    from sportsbet.graph.state import GraphState

    assert "prop_filters" in GraphState.__annotations__, (
        "'prop_filters' not found in GraphState.__annotations__. "
        "INFRA-01 gap not yet closed: add 'prop_filters: dict[str, Any] | None' "
        "to GraphState TypedDict in src/sportsbet/graph/state.py."
    )


@pytest.fixture(autouse=True)
def isolated_injury_sources(monkeypatch):
    # These tests exercise orchestration with fixture data, never live injury feeds.
    monkeypatch.setattr('sportsbet.graph.agents._fetch_sleeper_injuries', AsyncMock(return_value=[]))
