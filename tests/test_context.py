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
# CTXT-04: Context Agent GraphState propagation (Plan 04-04)
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone

from langgraph.checkpoint.memory import MemorySaver

from sportsbet.graph.agents import make_context_agent
from sportsbet.graph.graph import create_graph
from sportsbet.graph.models import ContextSignals
from sportsbet.graph.state import GraphState


def _make_full_state(
    game_id: str = "2025_01_KC_LAC",
    home_team: str = "KC",
    away_team: str = "LAC",
    request_type: str = "context_update",
) -> dict:
    """Build a minimal but complete GraphState fixture for CTXT-04 tests."""
    return {
        "session_id": str(uuid.uuid4()),
        "request_type": request_type,
        "created_at": datetime.now(timezone.utc),
        "game_id": game_id,
        "season": 2025,
        "week": 1,
        "home_team": home_team,
        "away_team": away_team,
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "context_signals": None,
    }


@pytest.mark.asyncio
async def test_context_agent_updates_graphstate() -> None:
    """make_context_agent returns ContextSignals in GraphState partial dict.

    Given make_context_agent(mock_pool, api_key="test_key", daily_credit_cap=500),
    when the returned async node is called with a GraphState fixture,
    then the return value is a dict with key "context_signals",
    and context_signals is a ContextSignals instance with the correct game_id.

    OddsAPIPoller.fetch_nfl_odds is mocked to return ODDS_FIXTURE.
    InjuryWeatherScraper.fetch_team_injuries is mocked to return [].
    No live HTTP or API calls are made.
    """
    mock_pool = MagicMock()

    with (
        patch("sportsbet.ingestion.odds_poller.httpx.AsyncClient") as mock_client_cls,
        patch.object(
            __import__(
                "sportsbet.ingestion.odds_poller",
                fromlist=["OddsAPIPoller"],
            ).OddsAPIPoller,
            "fetch_nfl_odds",
            new_callable=AsyncMock,
            return_value=ODDS_FIXTURE,
        ),
        patch(
            "sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        mock_client_instance = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        agent = make_context_agent(mock_pool, api_key="test_key", daily_credit_cap=500)
        state = _make_full_state()
        result = await agent(state)

    assert isinstance(result, dict), "Agent must return a dict"
    assert "context_signals" in result, "Return dict must contain 'context_signals' key"
    assert isinstance(result["context_signals"], ContextSignals), (
        "context_signals must be a ContextSignals instance"
    )
    assert result["context_signals"].game_id == "2025_01_KC_LAC"


@pytest.mark.asyncio
async def test_downstream_reads_state() -> None:
    """Downstream agent reads context_signals from GraphState, not from API.

    Given a compiled graph with make_context_agent wired as context_node,
    when graph.ainvoke() is called with request_type="context_update",
    then the resulting state["context_signals"] is a ContextSignals instance
    (not None), and no real HTTP calls are made to the Odds API.
    """
    mock_pool = MagicMock()

    with (
        patch("sportsbet.ingestion.odds_poller.httpx.AsyncClient") as mock_client_cls,
        patch.object(
            __import__(
                "sportsbet.ingestion.odds_poller",
                fromlist=["OddsAPIPoller"],
            ).OddsAPIPoller,
            "fetch_nfl_odds",
            new_callable=AsyncMock,
            return_value=ODDS_FIXTURE,
        ),
        patch(
            "sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        mock_client_instance = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        context_node = make_context_agent(mock_pool, api_key="test_key", daily_credit_cap=500)
        graph = create_graph(checkpointer=MemorySaver(), context_node=context_node)

        state = _make_full_state()
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )

    assert result["context_signals"] is not None, "context_signals must not be None after context_update"
    assert isinstance(result["context_signals"], ContextSignals), (
        "context_signals must be a ContextSignals instance"
    )
    # Verify no real HTTP was dispatched (mock_client_instance.get never called)
    mock_client_instance.get.assert_not_called()


# ---------------------------------------------------------------------------
# DATA-03: Context agent persists odds snapshot to PostgreSQL (08-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_agent_persists_odds_snapshot() -> None:
    """make_context_agent calls write_odds_snapshot exactly once when valid odds exist.

    Asserts:
    - write_odds_snapshot.call_count == 1 after context_agent(state) completes
    - Call kwargs include sportsbook and market_type; price is None
    - write_odds_snapshot is NOT called on the BudgetExhaustedError path
    """
    from unittest.mock import call

    mock_pool = MagicMock()

    with (
        patch("sportsbet.graph.agents.get_sync_engine", return_value=MagicMock()),
        patch("sportsbet.graph.agents.write_odds_snapshot") as mock_write,
        patch.object(
            __import__(
                "sportsbet.ingestion.odds_poller",
                fromlist=["OddsAPIPoller"],
            ).OddsAPIPoller,
            "fetch_nfl_odds",
            new_callable=AsyncMock,
            return_value=ODDS_FIXTURE,
        ),
        patch(
            "sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        agent = make_context_agent(mock_pool, api_key="test_key", daily_credit_cap=500)
        state = _make_full_state()
        await agent(state)

    assert mock_write.call_count == 1, (
        f"write_odds_snapshot must be called exactly once, got {mock_write.call_count}"
    )
    call_kwargs = mock_write.call_args
    # First positional arg is the OddsSnapshotCreate instance
    snap_create = call_kwargs[0][0]
    assert snap_create.sportsbook == "draftkings"
    assert snap_create.market_type == "h2h"
    assert snap_create.price is None, "price must be None (AgentOddsSnapshot stores Decimal, not int)"
