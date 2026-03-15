"""Tests for context and odds ingestion — CTXT-01 through CTXT-04.

CTXT-01: OddsAPIPoller — budget guard and HTTP fetch
CTXT-02: Staleness guard (is_stale)
CTXT-03: Context agent RSS/scraper integration (stub — Phase 4 Plan 03)
CTXT-04: Full pipeline integration (stub — Phase 4 Plan 03)

All Odds API HTTP calls are mocked — no live API credits consumed.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.ingestion.odds_poller import (
    BudgetExhaustedError,
    OddsAPIPoller,
    is_stale,
)

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

ODDS_FIXTURE = [
    {
        "id": "test_event_001",
        "sport_key": "americanfootball_nfl",
        "home_team": "Kansas City Chiefs",
        "away_team": "Los Angeles Chargers",
        "commence_time": "2025-10-05T17:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
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


# ---------------------------------------------------------------------------
# CTXT-01: OddsAPIPoller — budget guard and HTTP fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exhausted_raises() -> None:
    """Poller with _credits_remaining=0 raises BudgetExhaustedError without HTTP call.

    Budget guard must fire BEFORE any network call is made. We verify by
    patching httpx.AsyncClient and asserting it is never called.
    """
    with patch("sportsbet.ingestion.odds_poller.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        async with OddsAPIPoller(api_key="test-key", daily_credit_cap=500) as poller:
            # Force budget counter to exhausted state
            poller._credits_remaining = 0

            with pytest.raises(BudgetExhaustedError):
                await poller.fetch_nfl_odds()

        # Confirm no HTTP request was dispatched
        mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_odds_poller_writes_snapshot() -> None:
    """Mocked httpx returns valid payload + x-requests-remaining=499.

    After a successful fetch:
    - Return value is the parsed JSON list (ODDS_FIXTURE)
    - _credits_remaining is updated to 499
    """
    mock_response = MagicMock()
    mock_response.json.return_value = ODDS_FIXTURE
    mock_response.headers = {
        "x-requests-remaining": "499",
        "x-requests-last": "1",
        "x-requests-used": "1",
    }
    mock_response.raise_for_status = MagicMock()

    mock_async_client = AsyncMock()
    mock_async_client.get = AsyncMock(return_value=mock_response)

    with patch("sportsbet.ingestion.odds_poller.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        async with OddsAPIPoller(api_key="test-key", daily_credit_cap=500) as poller:
            result = await poller.fetch_nfl_odds()

        assert result == ODDS_FIXTURE
        assert poller._credits_remaining == 499


# ---------------------------------------------------------------------------
# CTXT-02: Staleness guard
# ---------------------------------------------------------------------------


def test_staleness_guard_rejects_stale() -> None:
    """is_stale() returns True when snapped_at is 6 minutes ago (threshold=5)."""
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=6)
    assert is_stale(stale_time, threshold_minutes=5) is True


def test_staleness_guard_passes_fresh() -> None:
    """is_stale() returns False when snapped_at is 2 minutes ago (threshold=5)."""
    fresh_time = datetime.now(timezone.utc) - timedelta(minutes=2)
    assert is_stale(fresh_time, threshold_minutes=5) is False


# ---------------------------------------------------------------------------
# CTXT-03 stubs — Phase 4 Plan 03 (Context Agent RSS/scraper)
# ---------------------------------------------------------------------------


def test_context_agent_parses_injury_report() -> None:
    """CTXT-03 stub: Context agent extracts binary injury state from RSS feed."""
    pytest.fail("CTXT-03 not yet implemented — stub for Phase 4 Plan 03")


def test_context_agent_updates_game_state() -> None:
    """CTXT-03 stub: Context agent writes parsed injury state to GraphState."""
    pytest.fail("CTXT-03 not yet implemented — stub for Phase 4 Plan 03")


# ---------------------------------------------------------------------------
# CTXT-04 stubs — Phase 4 Plan 03 (Full pipeline integration)
# ---------------------------------------------------------------------------


def test_full_pipeline_odds_to_ev_signal() -> None:
    """CTXT-04 stub: Full pipeline — odds -> arbitrage agent -> EVSignal."""
    pytest.fail("CTXT-04 not yet implemented — stub for Phase 4 Plan 03")


def test_full_pipeline_stale_odds_rejected() -> None:
    """CTXT-04 stub: Full pipeline rejects stale odds before Arbitrage Agent."""
    pytest.fail("CTXT-04 not yet implemented — stub for Phase 4 Plan 03")
