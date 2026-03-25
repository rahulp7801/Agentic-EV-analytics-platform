"""Wave 0 TDD test stubs for GraphState.situational_params injection (Phase 18 — SC-3).

Tests are RED until:
- Task 2 adds situational_params field to GraphState in state.py
- Task 3 wires _extract_situational_params into make_context_agent in agents.py
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.graph.state import GraphState


# ---------------------------------------------------------------------------
# GraphState field presence test
# ---------------------------------------------------------------------------


def test_graph_state_has_situational_params() -> None:
    """GraphState TypedDict declares 'situational_params' as a field annotation."""
    annotations = GraphState.__annotations__
    assert "situational_params" in annotations, (
        "GraphState is missing 'situational_params' field — add it to state.py (Phase 18 — SC-3)"
    )


# ---------------------------------------------------------------------------
# make_context_agent injection test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_agent_returns_situational_params() -> None:
    """make_context_agent closure returns a dict that contains 'situational_params' key.

    The key may be None when there are no Out/Inactive injury flags, but it must
    always be present in the returned partial state dict.
    """
    from sportsbet.graph.agents import make_context_agent

    # --- Build a minimal mock pool ---
    mock_conn = AsyncMock()
    mock_conn.executemany = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value=None)
    # pool.acquire() used as async context manager
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock(return_value=False)))

    # --- Build a minimal GraphState dict ---
    state: dict[str, Any] = {
        "session_id": "test-session-sc3",
        "game_id": "2024_01_LAL_GSW",
        "home_team": "LAL",
        "away_team": "GSW",
        "sport": "nba",
        "injury_flags": {},
    }

    # --- Patch all network-touching callables ---
    with (
        patch("sportsbet.graph.agents.OddsAPIPoller") as mock_poller_cls,
        patch("sportsbet.graph.agents.InjuryWeatherScraper") as mock_scraper_cls,
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.graph.agents.write_player_prop_snapshot"),
        patch("sportsbet.graph.agents.get_sync_engine"),
    ):
        # OddsAPIPoller: async context manager that returns a mock poller
        mock_poller = AsyncMock()
        mock_poller.fetch_nba_odds = AsyncMock(return_value=[])
        mock_poller.fetch_nfl_odds = AsyncMock(return_value=[])
        mock_poller.fetch_player_props = AsyncMock(return_value=[])
        mock_poller_cls.return_value.__aenter__ = AsyncMock(return_value=mock_poller)
        mock_poller_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # InjuryWeatherScraper: sync constructor, async methods
        mock_scraper = AsyncMock()
        mock_scraper.fetch_team_injuries = AsyncMock(return_value=[])
        mock_scraper.write_injury_reports = AsyncMock(return_value=None)
        mock_scraper_cls.return_value = mock_scraper

        context_fn = make_context_agent(
            pool=mock_pool,  # type: ignore[arg-type]
            api_key="test-key",
            daily_credit_cap=100,
        )
        result = await context_fn(state)  # type: ignore[arg-type]

    assert "situational_params" in result, (
        "make_context_agent return dict is missing 'situational_params' key — "
        "add the field injection to agents.py (Phase 18 — SC-3)"
    )
