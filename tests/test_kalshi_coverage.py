"""Synthetic provider protocol fixtures exercise the actual public reader/collector."""
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from sportsbet import market_watch

NOW=datetime(2026,9,11,tzinfo=timezone.utc)


def milestone(number):
    event=f'KXNFLGAME-TEST{number}'
    return dict(id=str(number),title=f'Game {number}',start_date=(NOW+timedelta(days=1)).isoformat(),
        related_event_tickers=[event],
        details=dict(league='NFL',main_game_event_ticker=f'KXNFLGAME-TEST{number}',
            home_team_id='00000000-0000-0000-0000-000000000001',away_team_id='00000000-0000-0000-0000-000000000002'))


@pytest.mark.asyncio
async def test_discovery_paginates_deduplicates_and_rejects_conflicting_identity():
    duplicate=milestone(1)
    conflicting=milestone(2)|{'start_date':(NOW+timedelta(days=2)).isoformat()}
    reader=AsyncMock()
    reader.milestones.side_effect=[{'milestones':[duplicate,milestone(2)],'cursor':'next'},
        {'milestones':[duplicate,conflicting,milestone(3)],'cursor':''}]
    games,pages,failures,complete=await market_watch.discover_kalshi_games(reader,'nfl',NOW)
    assert [game['id'] for game in games]==['1','3']
    assert len(pages)==2 and len(failures)==1 and not complete
    assert reader.milestones.call_args_list[1].kwargs=={'limit':500,'cursor':'next'}


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['failure','repeat','cap','invalid'])
async def test_discovery_keeps_prior_results_and_exposes_incomplete_pages(mode):
    reader=AsyncMock()
    first={'milestones':[milestone(1)],'cursor':'next'}
    reader.milestones.side_effect={
        'failure':[first,RuntimeError('provider URL with secret')],
        'repeat':[first,{'milestones':[],'cursor':'next'}],
        'cap':[first,{'milestones':[],'cursor':'second'},{'milestones':[],'cursor':'third'}],
        'invalid':[{'milestones':[milestone(1)],'cursor':[]}],
    }[mode]
    games,pages,failures,complete=await market_watch.discover_kalshi_games(reader,'nfl',NOW)
    assert [game['id'] for game in games]==['1'] and not complete
    assert reader.milestones.await_count<=3
    assert bool(failures)==(mode!='cap')
    assert 'secret' not in str(failures)


@pytest.mark.asyncio
async def test_one_failed_game_or_market_does_not_discard_other_observations(monkeypatch):
    client=httpx.AsyncClient
    calls=[]
    def handle(request):
        calls.append(request)
        assert request.method=='GET' and 'KALSHI-ACCESS-KEY' not in request.headers
        path=request.url.path
        if path.endswith('/milestones'):
            assert request.url.params['type']=='football_game' and request.url.params['limit']=='500'
            return httpx.Response(200,json={'milestones':[milestone(i) for i in range(1,5)],'cursor':''})
        if '/structured_targets/' in path:
            return httpx.Response(200,json={'structured_target':{'name':'Team '+path[-1]}})
        if '/events/' in path and 'fee_changes' not in path:
            event=path.rsplit('/',1)[1]
            if event.endswith('2'):return httpx.Response(503)
            return httpx.Response(200,json={'event':{'event_ticker':event,'series_ticker':'KXNFLGAME'},
                'markets':[dict(ticker=event+'-HOME',event_ticker=event,status='active')]})
        if path.endswith('/orderbook'):
            return httpx.Response(200,json={'orderbook_fp':{'yes_dollars':[['.5','10']],'no_dollars':[['.49','10']]}})
        if path.endswith('/markets'):
            return httpx.Response(200,json={'markets':[],'cursor':''})
        if '/markets/' in path:
            ticker=path.rsplit('/',1)[1]
            if 'TEST3' in ticker:return httpx.Response(503)
            if 'TEST4' in ticker:ticker='KXNFLGAME-WRONG-HOME'
            return httpx.Response(200,json={'market':dict(ticker=ticker,event_ticker=ticker.rsplit('-',1)[0],
                title=ticker,status='active',notional_value_dollars='1.0000')})
        return httpx.Response(503)  # Missing fee/ESPN metadata must not discard valid quotes.
    transport=httpx.MockTransport(handle)
    monkeypatch.setattr(httpx,'AsyncClient',lambda *args,**kwargs:client(*args,**(kwargs|{'transport':transport})))
    source=await market_watch.kalshi_games('nfl',NOW,20)
    assert source['status']=='degraded' and source['partial_coverage'] is True
    assert source['coverage']==dict(discovery_complete=True,discovered_games=4,attempted_games=4,
        observed_games=3,event_failed_games=1,market_failed_games=2,sample_complete_games=1,
        quoted_games=1,failed_games=3,omitted_markets=0,
        prop_discovery_complete=True,prop_series_observed=4,prop_series_expected=4,
        prop_open_markets=0,prop_open_events=0,prop_linked_markets=0,prop_linked_events=0,
        prop_structured_quote_markets=0,prop_two_sided_quote_markets=0,
        prop_player_resolved_quote_markets=0,prop_fee_contexts_expected=0,
        prop_fee_contexts_observed=0,prop_fee_failures=0)
    assert source['coverage']['attempted_games'] == (
        source['coverage']['observed_games'] + source['coverage']['event_failed_games'])
    assert source['coverage']['observed_games'] == (
        source['coverage']['sample_complete_games'] + source['coverage']['market_failed_games'])
    rows=market_watch.comparisons(dict(sport='nfl',schema_version=2,captured_at=datetime.now(timezone.utc).isoformat(),sources={'kalshi':source}))
    assert len(rows)==1 and rows[0]['identity']=='KXNFLGAME-TEST1-HOME'
    assert rows[0]['execution_ready'] is False
    assert any(failure['error_type']=='ValueError' for failure in source['failures'])
    assert not any('api_keys' in request.url.path for request in calls)


@pytest.mark.asyncio
async def test_default_sample_reaches_later_games_and_reports_the_bound(monkeypatch):
    class Reader:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def series(self,*args):raise RuntimeError('Unavailable optional fee metadata')
        async def series_fee_changes(self,*args):return {}
        async def milestones(self,*args,**kwargs):return {'milestones':[milestone(i) for i in range(25)],'cursor':''}
        async def markets(self,*args,**kwargs):return {'markets':[],'cursor':''}
        async def target(self,*args):return {'name':'Team'}
        async def event(self,event):return {'event':{'event_ticker':event,'series_ticker':'KXNFLGAME'},'markets':[]}
    client=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda *args,**kwargs:client(*args,**kwargs,transport=httpx.MockTransport(lambda request:httpx.Response(503))))
    monkeypatch.setattr(market_watch,'KalshiReader',Reader)
    source=await market_watch.kalshi_games('nfl',NOW,market_watch.DEFAULT_GAME_LIMIT)
    assert len(source['games'])==20 and source['coverage']['discovered_games']==25
    assert source['partial_coverage'] is True and source['status']=='observed'
    assert source['coverage']['quoted_games']==0  # Inspected metadata is not an invented price.
