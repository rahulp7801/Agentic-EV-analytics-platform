from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from sportsbet.ingestion.kalshi import KalshiReader
from sportsbet.market_watch import book_quotes, comparisons

NOW = datetime(2026,9,11,tzinfo=timezone.utc)


def evidence():
    event = dict(id='game',home_team='Home',away_team='Away',commence_time='2026-09-13T17:00:00Z',
        bookmakers=[dict(key='book',last_update=NOW.isoformat(),markets=[dict(key='h2h',outcomes=[
            dict(name='Home',price=110),dict(name='Away',price=110)])])])
    return dict(sport='nfl',captured_at=NOW.isoformat(),sources={'sportsbook':{'events':[event]}})


def test_gross_price_gap_never_becomes_profit_or_verified_arbitrage():
    row, = comparisons(evidence())
    assert Decimal(row['gross_gap_to_one_dollar']) > 0
    assert row['status']=='unverified' and row['execution_ready'] is False
    assert row['realized_profit'] is None and row['fee_adjusted_profit'] is None
    assert 'tie/void' in row['reasons'][0]


def test_h2h_quotes_require_complete_teams_observation_time_and_current_window():
    event = evidence()['sources']['sportsbook']['events'][0]
    assert len(book_quotes(event,NOW))==2
    for invalid_time in ['2026-09-10T23:00:00Z','2026-09-11T01:00:00Z','2026-09-11T00:00:00']:
        changed=deepcopy(event)
        changed['bookmakers'][0]['last_update']=invalid_time
        assert book_quotes(changed,NOW)==[]
    changed=deepcopy(event)
    changed['commence_time']='2026-10-01T00:00:00Z'
    assert book_quotes(changed,NOW)==[]
    event['bookmakers'][0]['markets'][0]['outcomes'].append(dict(name='Draw',price=1000))
    assert book_quotes(event,NOW)==[]  # Cannot silently drop a third outcome.


@pytest.mark.asyncio
async def test_milestones_use_verified_league_filter_and_public_get():
    def handle(request):
        assert request.method=='GET' and request.url.params['competition']=='NFL'
        assert 'KALSHI-ACCESS-KEY' not in request.headers
        return httpx.Response(200,json={'milestones':[], 'cursor':''})
    async with KalshiReader(transport=httpx.MockTransport(handle)) as reader:
        assert (await reader.milestones('nfl',NOW))['milestones']==[]
        with pytest.raises(ValueError):
            await reader.milestones('nfl',NOW.replace(tzinfo=None))


def test_cross_venue_requires_unique_exact_team_and_start_match():
    data=evidence()
    snap=dict(market=dict(ticker='KX-TEST-H',title='Home wins',notional_value_dollars='1.0000',
        custom_strike={'football_team':'home'}),same_contract_pair=None,
        received_at=NOW.isoformat(),yes_asks=[('0.4','20')],no_asks=[])
    data['sources']['kalshi']=dict(targets={'home':{'name':'Home'},'away':{'name':'Away'}}, games=[dict(
        milestone=dict(title='Home vs Away',start_date='2026-09-13T17:00:00Z',
            details={'home_team_id':'home','away_team_id':'away'}),snapshots=[snap])])
    cross=[r for r in comparisons(data) if r['kind']=='kalshi_sportsbook']
    assert len(cross)==1 and cross[0]['legs'][1]['team']=='Away'
    assert cross[0]['execution_ready'] is False
    changed=deepcopy(data)
    changed['sources']['kalshi']['games'][0]['milestone']['start_date']='2026-09-13T18:00:00Z'
    assert not [r for r in comparisons(changed) if r['kind']=='kalshi_sportsbook']
    changed=deepcopy(data)
    changed['sources']['kalshi']['targets']['home']['name']='Home Other'
    assert not [r for r in comparisons(changed) if r['kind']=='kalshi_sportsbook']
    changed=deepcopy(data)
    duplicate=deepcopy(changed['sources']['sportsbook']['events'][0]);duplicate['id']='duplicate'
    changed['sources']['sportsbook']['events'].append(duplicate)
    assert not [r for r in comparisons(changed) if r['kind']=='kalshi_sportsbook']


@pytest.mark.asyncio
async def test_unavailable_source_is_retained_without_discarding_other_evidence(monkeypatch,tmp_path):
    from sportsbet import market_watch
    async def books(*args): return {'status':'observed','events':[]}
    async def kalshi(*args): return {'status':'observed','games':[]}
    async def blocked(*args): raise RuntimeError('provider URL could contain secrets')
    monkeypatch.setattr(market_watch,'sportsbooks',books)
    monkeypatch.setattr(market_watch,'kalshi_games',kalshi)
    monkeypatch.setattr(market_watch,'capture_projections',blocked)
    monkeypatch.chdir(tmp_path)
    report,path=await market_watch.run('nfl',25,1,False)
    assert path.exists()
    assert report['sources']['sportsbook']['status']=='observed'
    assert report['sources']['prizepicks']['status']=='unavailable'
    assert 'secrets' not in path.read_text()
