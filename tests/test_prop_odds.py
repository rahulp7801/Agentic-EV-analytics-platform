"""TDD tests for fetch_player_props() and write_player_prop_snapshot() (Phase 10 Plan 01).

These tests are written RED — they import from modules that do not yet export
the tested functions/classes. Tests will fail until Task 2 implements them.

Test coverage:
- fetch_player_props("nfl"): two-step event-list + per-event fetch with mocked httpx
- write_player_prop_snapshot(): DB write with mocked engine
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_EVENTS_FIXTURE: list[dict[str, Any]] = [
    {"id": "evt_abc123", "sport_key": "americanfootball_nfl", "home_team": "Kansas City Chiefs"},
]

_PROPS_FIXTURE: dict[str, Any] = {
    "id": "evt_abc123",
    "bookmakers": [
        {
            "key": "draftkings",
            "markets": [
                {
                    "key": "player_pass_yds",
                    "outcomes": [
                        {"name": "Patrick Mahomes", "description": "Over", "price": -115, "point": 287.5},
                    ],
                }
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# fetch_player_props tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_nfl_player_props() -> None:
    """fetch_player_props('nfl') returns list[dict] with expected event structure.

    Mocks httpx.AsyncClient to return fixture events list on /events call and
    fixture props response on per-event /events/{id}/odds call.
    """
    from sportsbet.ingestion.odds_poller import OddsAPIPoller

    events_response = MagicMock()
    events_response.raise_for_status = MagicMock()
    events_response.json.return_value = _EVENTS_FIXTURE
    events_response.headers = {"x-requests-remaining": "490"}

    props_response = MagicMock()
    props_response.raise_for_status = MagicMock()
    props_response.json.return_value = _PROPS_FIXTURE
    props_response.headers = {"x-requests-remaining": "489"}

    mock_client = AsyncMock()
    # First call -> events list; second call -> per-event props
    mock_client.get.side_effect = [events_response, props_response]

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_cm):
        async with OddsAPIPoller(api_key="test_key", daily_credit_cap=500) as poller:
            result = await poller.fetch_player_props("nfl")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["id"] == "evt_abc123"


# ---------------------------------------------------------------------------
# write_player_prop_snapshot tests
# ---------------------------------------------------------------------------


def test_write_player_prop_snapshot() -> None:
    """write_player_prop_snapshot() inserts a row into player_prop_snapshots.

    Mocks SQLAlchemy engine to verify INSERT is called without a real DB.
    """
    from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, write_player_prop_snapshot

    snapshot = PlayerPropSnapshotCreate(
        sport="nfl",
        game_id="2024_01_KC_BUF",
        player_name="Patrick Mahomes",
        sportsbook="DraftKings",
        prop_type="pass_yds",
        line=Decimal("287.5"),
        price=-115,
        implied_probability=Decimal(str(round(115 / (115 + 100), 6))),
        side="Over",
        snapped_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
        game_start_time=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )

    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 1
    mock_conn.execute.return_value = mock_result
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_conn

    row_id = write_player_prop_snapshot(snapshot, engine=mock_engine)
    assert row_id == 1
    mock_conn.execute.assert_called_once()


@pytest.mark.parametrize(
    'change',
    [
        {'sport': 'mlb'},
        {'game_id': None},
        {'game_id': ' '},
        {'player_name': ' '},
        {'sportsbook': ''},
        {'prop_type': ''},
        {'line': None},
        {'line': Decimal('NaN')},
        {'line': Decimal('-0.5')},
        {'price': None},
        {'price': 99},
        {'implied_probability': Decimal('0')},
        {'implied_probability': Decimal('NaN')},
        {'side': None},
        {'side': 'Yes'},
        {'game_start_time': None},
        {'snapped_at': datetime(2026, 9, 12)},
        {'game_start_time': datetime(2026, 9, 13)},
        {'game_start_time': datetime(2026, 9, 12, tzinfo=timezone.utc)},
    ],
)
def test_write_rejects_incomplete_or_non_pregame_snapshots(change) -> None:
    from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, write_player_prop_snapshot

    snapshot = PlayerPropSnapshotCreate(
        sport='nfl', game_id='event', player_name='Player', sportsbook='book',
        prop_type='player_pass_yds', line=Decimal('249.5'), price=-110,
        implied_probability=Decimal('0.523809'), side='Over',
        snapped_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
        game_start_time=datetime(2026, 9, 13, tzinfo=timezone.utc),
    ).model_copy(update=change)
    engine = MagicMock()
    with pytest.raises(ValueError, match='complete pregame quote'):
        write_player_prop_snapshot(snapshot, engine=engine)
    engine.begin.assert_not_called()
