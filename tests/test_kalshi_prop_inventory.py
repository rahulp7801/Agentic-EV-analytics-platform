from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from sportsbet import market_watch


NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def game(number: int, *events: str) -> dict:
    return {
        'id': f'00000000-0000-0000-0000-00000000000{number}',
        'start_date': (NOW + timedelta(days=1)).isoformat(),
        'related_event_tickers': list(events),
        'details': {'league': 'NFL'},
    }


def market(series: str, event: str, suffix: str) -> dict:
    return {
        'ticker': f'{event}-{suffix}',
        'event_ticker': event,
        'status': 'active',
        'market_type': 'binary',
        'notional_value_dollars': '1.0000',
    }


@pytest.mark.asyncio
async def test_prop_inventory_links_structured_events_and_reports_complete_pages():
    passing = 'KXNFLPASSYDS-26SEP13ATLPIT'
    rushing = 'KXNFLRSHYDS-26SEP13ATLPIT'
    reader = AsyncMock()

    async def pages(series, *, limit, cursor=None):
        assert limit == market_watch.PROP_PAGE_LIMIT
        if series == 'KXNFLPASSYDS':
            if cursor is None:
                return {'markets': [market(series, passing, 'PLAYER-250')], 'cursor': 'next'}
            assert cursor == 'next'
            return {'markets': [market(series, passing, 'PLAYER-275')], 'cursor': ''}
        if series == 'KXNFLRSHYDS':
            return {'markets': [market(series, rushing, 'PLAYER-50')], 'cursor': ''}
        return {'markets': [], 'cursor': ''}

    reader.markets.side_effect = pages
    result = await market_watch.kalshi_prop_inventory(
        reader,
        'nfl',
        [game(1, passing, rushing, 'KXNFLTOTAL-26SEP13ATLPIT')],
    )

    assert result['status'] == 'observed'
    assert result['partial_coverage'] is False
    assert result['coverage'] == {
        'series_expected': 4,
        'series_observed': 4,
        'open_markets': 3,
        'open_events': 2,
        'linked_markets': 3,
        'linked_events': 2,
        'discovery_complete': True,
    }
    assert result['series']['KXNFLPASSYDS']['pages'] == 2
    assert result['series']['KXNFLPASSYDS']['linked_markets'] == 2
    assert result['series']['KXNFLPASSYDS']['response_sha256']
    assert 'markets' not in result['series']['KXNFLPASSYDS']
    assert reader.markets.await_count == 5


@pytest.mark.asyncio
async def test_prop_inventory_preserves_counts_but_fails_closed_on_incomplete_or_bad_pages():
    event = 'KXNFLPASSYDS-26SEP13ATLPIT'
    reader = AsyncMock()

    async def pages(series, *, limit, cursor=None):
        if series == 'KXNFLPASSYDS':
            if cursor is None:
                return {'markets': [market(series, event, 'PLAYER-250')], 'cursor': 'repeat'}
            return {'markets': [], 'cursor': 'repeat'}
        if series == 'KXNFLRSHYDS':
            return {'markets': 'not-a-list', 'cursor': ''}
        if series == 'KXNFLRECYDS':
            raise RuntimeError('provider URL with private material')
        return {'markets': [], 'cursor': ''}

    reader.markets.side_effect = pages
    result = await market_watch.kalshi_prop_inventory(reader, 'nfl', [game(1, event)])

    assert result['status'] == 'degraded'
    assert result['partial_coverage'] is True
    assert result['coverage']['linked_markets'] == 1
    assert result['coverage']['discovery_complete'] is False
    assert result['series']['KXNFLPASSYDS']['complete'] is False
    assert result['series']['KXNFLRSHYDS']['status'] == 'invalid'
    assert result['series']['KXNFLRECYDS']['status'] == 'unavailable'
    assert 'private material' not in str(result)
    assert reader.markets.await_count <= 6


@pytest.mark.asyncio
async def test_prop_inventory_rejects_cross_game_event_conflicts():
    event = 'KXNFLPASSYDS-26SEP13ATLPIT'
    reader = AsyncMock()
    async def pages(series, **kwargs):
        return {'markets': [market(series, event, 'PLAYER-250')] if series == 'KXNFLPASSYDS' else [], 'cursor': ''}
    reader.markets.side_effect = pages
    result = await market_watch.kalshi_prop_inventory(
        reader,
        'nfl',
        [game(1, event), game(2, event)],
    )
    assert result['status'] == 'degraded'
    assert result['coverage']['open_markets'] == 1
    assert result['coverage']['linked_markets'] == 0
    assert result['coverage']['discovery_complete'] is False
    assert result['failures'] == [{'stage': 'prop_link', 'error_type': 'ConflictingEvent'}]


@pytest.mark.asyncio
async def test_prop_inventory_validates_sport_and_milestone_shape():
    reader = AsyncMock()
    with pytest.raises(ValueError):
        await market_watch.kalshi_prop_inventory(reader, 'mlb', [])
    reader.markets.return_value = {'markets': [], 'cursor': ''}
    result = await market_watch.kalshi_prop_inventory(reader, 'nfl', [{'id': 'game'}])
    assert result['status'] == 'degraded'
    assert result['coverage']['discovery_complete'] is False
    assert result['failures'] == [{'stage': 'prop_link', 'error_type': 'InvalidMilestone'}]
    assert reader.markets.await_count == 4
