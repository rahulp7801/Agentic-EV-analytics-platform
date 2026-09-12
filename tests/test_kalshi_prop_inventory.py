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
        'details': {'league': 'NFL','home_team_id':'10000000-0000-0000-0000-000000000001',
            'away_team_id':'20000000-0000-0000-0000-000000000002'},
    }


def market(series: str, event: str, suffix: str) -> dict:
    return {
        'ticker': f'{event}-{suffix}',
        'event_ticker': event,
        'status': 'active',
        'market_type': 'binary',
        'notional_value_dollars': '1.0000',
        'primary_participant_key':'football_player',
        'custom_strike':{'football_player':'30000000-0000-0000-0000-000000000003',
            'football_team':'10000000-0000-0000-0000-000000000001'},
        'strike_type':'greater','floor_strike':249.5,
        'occurrence_datetime':(NOW+timedelta(days=1)).isoformat(),
        'yes_bid_dollars':'0.4000','yes_bid_size_fp':'12.00',
        'yes_ask_dollars':'0.4500','yes_ask_size_fp':'10.00',
        'no_bid_dollars':'0.5500','no_ask_dollars':'0.6000',
        'rules_primary':'Primary settlement rule.','rules_secondary':'Secondary settlement rule.',
    }


def configure_targets(reader: AsyncMock) -> None:
    reader.targets.return_value={'structured_targets':[{
        'id':'30000000-0000-0000-0000-000000000003','name':'Player Name','type':'football_player',
        'details':{'league':'NFL','team_id':'10000000-0000-0000-0000-000000000001'}}],'cursor':''}


@pytest.mark.asyncio
async def test_prop_inventory_links_structured_events_and_reports_complete_pages():
    passing = 'KXNFLPASSYDS-26SEP13ATLPIT'
    rushing = 'KXNFLRSHYDS-26SEP13ATLPIT'
    reader = AsyncMock()
    configure_targets(reader)

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
        'structured_quote_markets': 3,
        'two_sided_quote_markets': 3,
        'player_resolved_quote_markets': 3,
        'discovery_complete': True,
    }
    assert result['series']['KXNFLPASSYDS']['pages'] == 2
    assert result['series']['KXNFLPASSYDS']['linked_markets'] == 2
    assert result['series']['KXNFLPASSYDS']['response_sha256']
    assert 'markets' not in result['series']['KXNFLPASSYDS']
    assert len(result['quotes'])==3
    quote=result['quotes'][0]
    assert {k:v for k,v in quote.items() if k not in ('request_started_at','received_at')} == {
        'ticker':f'{passing}-PLAYER-250','event_ticker':passing,'series_ticker':'KXNFLPASSYDS',
        'milestone_id':game(1)['id'],'scheduled_game_start_time':(NOW+timedelta(days=1)).isoformat(),
        'market_occurrence_time':(NOW+timedelta(days=1)).isoformat(),
        'prop_type':'pass_yds','player_target_id':'30000000-0000-0000-0000-000000000003',
        'team_target_id':'10000000-0000-0000-0000-000000000001','strike_type':'greater','line':'249.5',
        'yes_ask':{'cost':'0.4500','displayed_size':'10.00'},
        'no_ask':{'cost':'0.6000','displayed_size':'12.00'},
        'market_sha256':market_watch.digest(market('KXNFLPASSYDS',passing,'PLAYER-250')),
        'source_page_sha256':quote['source_page_sha256'],
        'rules_sha256':market_watch.digest({'primary':'Primary settlement rule.','secondary':'Secondary settlement rule.'}),
        'settlement_equivalent':False,'execution_ready':False}
    assert datetime.fromisoformat(quote['request_started_at']) <= datetime.fromisoformat(quote['received_at'])
    target=result['targets']['30000000-0000-0000-0000-000000000003']
    assert target['player_name']=='Player Name'
    assert target['team_target_id']=='10000000-0000-0000-0000-000000000001'
    assert target['target_sha256']==market_watch.digest(reader.targets.return_value['structured_targets'][0])
    assert datetime.fromisoformat(target['target_request_started_at']) <= datetime.fromisoformat(target['target_received_at'])
    assert reader.markets.await_count == 5


@pytest.mark.asyncio
async def test_prop_inventory_preserves_counts_but_fails_closed_on_incomplete_or_bad_pages():
    event = 'KXNFLPASSYDS-26SEP13ATLPIT'
    reader = AsyncMock()
    configure_targets(reader)

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
    assert result['coverage']['structured_quote_markets'] == 1
    assert result['coverage']['player_resolved_quote_markets'] == 1
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


@pytest.mark.asyncio
@pytest.mark.parametrize('change',[{'yes_ask_dollars':'0.4600'},
    {'custom_strike':{'football_player':'30000000-0000-0000-0000-000000000003',
        'football_team':'90000000-0000-0000-0000-000000000009'}},
    {'primary_participant_key':'football_team'}])
async def test_prop_inventory_rejects_inconsistent_quote_or_structured_identity(change):
    event='KXNFLPASSYDS-26SEP13ATLPIT';reader=AsyncMock()
    item=market('KXNFLPASSYDS',event,'PLAYER-250')|change
    async def pages(series,**kwargs):
        return {'markets':[item] if series=='KXNFLPASSYDS' else [],'cursor':''}
    reader.markets.side_effect=pages
    result=await market_watch.kalshi_prop_inventory(reader,'nfl',[game(1,event)])
    assert result['status']=='degraded' and result['partial_coverage'] is True
    assert result['coverage']['structured_quote_markets']==0
    assert result['series']['KXNFLPASSYDS']['status']=='invalid'
    assert result['failures']==[{'stage':'prop_discovery','series':'KXNFLPASSYDS','error_type':'ValueError'}]


@pytest.mark.asyncio
async def test_prop_target_failure_retains_quotes_but_blocks_cross_provider_identity():
    event='KXNFLPASSYDS-26SEP13ATLPIT';reader=AsyncMock()
    async def pages(series,**kwargs):
        return {'markets':[market(series,event,'PLAYER-250')] if series=='KXNFLPASSYDS' else [],'cursor':''}
    reader.markets.side_effect=pages
    reader.targets.return_value={'structured_targets':[],'cursor':''}
    result=await market_watch.kalshi_prop_inventory(reader,'nfl',[game(1,event)])
    assert result['status']=='degraded' and result['coverage']['structured_quote_markets']==1
    assert result['coverage']['player_resolved_quote_markets']==0
    assert 'player_name' not in result['quotes'][0]
    assert result['targets']=={}
    assert result['failures']==[{'stage':'prop_targets','error_type':'ValueError'}]
