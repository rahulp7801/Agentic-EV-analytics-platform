"""Tests for context and odds ingestion — CTXT-01 through CTXT-04.

CTXT-01: OddsAPIPoller — budget guard and HTTP fetch
CTXT-02: Staleness guard (is_stale)
CTXT-03: InjuryWeatherScraper — ESPN Core API parsing and DB write
CTXT-04: Full pipeline integration (stub — Phase 4 Plan 04)

All Odds API HTTP calls are mocked — no live API credits consumed.
All ESPN API calls are mocked — no live network calls in CTXT-03 tests.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.ingestion.odds_poller import (
    BudgetExhaustedError,
    OddsAPIPoller,
    is_stale,
)
from sportsbet.ingestion.scraper import (
    TEAM_ABBR_TO_ESPN_ID,
    InjuryWeatherScraper,
    parse_espn_injury_item,
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
# CTXT-03: InjuryWeatherScraper — ESPN Core API (Plan 04-03 TDD)
# ---------------------------------------------------------------------------

ESPN_FIXTURE = {
    "items": [
        {
            "athlete": {
                "displayName": "Patrick Mahomes",
                "position": {"abbreviation": "QB"},
            },
            "status": "Questionable",
        },
        {
            "athlete": {
                "displayName": "Travis Kelce",
                "position": {"abbreviation": "TE"},
            },
            "status": "Out",
        },
    ]
}


@pytest.mark.asyncio
async def test_espn_injury_parsing() -> None:
    """ESPN Core API JSON fixture is parsed into InjuryReport-compatible dicts.

    Given a mocked ESPN Core API JSON response with 2 players (one "Out", one
    "Questionable"), parse_espn_injury_item() on each item returns a dict with
    keys: player_name, status, position.
    Fields absent from the fixture must fall back to "Unknown" (not raise KeyError).
    """
    items = ESPN_FIXTURE["items"]
    assert len(items) == 2

    result_0 = parse_espn_injury_item(items[0])
    assert result_0["player_name"] == "Patrick Mahomes"
    assert result_0["status"] == "Questionable"
    assert result_0["position"] == "QB"

    result_1 = parse_espn_injury_item(items[1])
    assert result_1["player_name"] == "Travis Kelce"
    assert result_1["status"] == "Out"
    assert result_1["position"] == "TE"

    # Missing fields must fall back to "Unknown"
    empty_item: dict[str, object] = {}
    fallback = parse_espn_injury_item(empty_item)
    assert fallback["player_name"] == "Unknown"
    assert fallback["status"] == "Unknown"
    assert fallback["position"] == "Unknown"


@pytest.mark.asyncio
async def test_scraper_writes_injury_report() -> None:
    """Scraper writes a structured InjuryReport row to the injury_reports table.

    Given a mocked asyncpg pool and 1 parsed injury dict,
    when write_injury_reports(pool, injuries, team_abbr="KC") is called,
    then conn.execute is called once with an INSERT INTO injury_reports statement
    and the correct positional parameters including source='espn_core_api'.
    """
    import httpx
    from unittest.mock import MagicMock

    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    injuries = [
        {"player_name": "Patrick Mahomes", "status": "Questionable", "position": "QB"},
    ]

    async with httpx.AsyncClient() as client:
        scraper = InjuryWeatherScraper(client)
        count = await scraper.write_injury_reports(
            pool=mock_pool,
            injuries=injuries,
            team_abbr="KC",
        )

    assert count == 1
    assert mock_conn.execute.call_count == 1
    call_args = mock_conn.execute.call_args
    sql_str: str = call_args[0][0]
    assert "INSERT INTO injury_reports" in sql_str
    # positional params appended after the SQL string (no f-string injection)
    params = call_args[0][1:]
    assert "espn_core_api" in params, "source must be 'espn_core_api'"


# ---------------------------------------------------------------------------
# CTXT-04 stubs — Phase 4 Plan 04 (Context Agent GraphState propagation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_agent_updates_graphstate() -> None:
    """make_context_agent returns ContextSignals in GraphState partial dict."""
    pytest.fail("not implemented — Plan 04-04 will implement make_context_agent")


@pytest.mark.asyncio
async def test_downstream_reads_state() -> None:
    """Downstream agent reads context_signals from GraphState, not from API."""
    pytest.fail("not implemented — Plan 04-04 will verify state propagation")
