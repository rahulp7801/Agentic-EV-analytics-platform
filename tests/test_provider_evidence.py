from copy import deepcopy
from datetime import datetime, timezone

import pytest

from sportsbet.ingestion.prop_odds import parse_event_quotes, prop_quote_record_sha256
from sportsbet.ingestion.prizepicks import parse_projections


def event():
    return dict(id='event', commence_time='2026-09-13T17:00:00Z', bookmakers=[dict(key='book',
        markets=[dict(key='player_pass_yds',last_update='2026-09-10T15:00:00Z',
            outcomes=[dict(name='Over',description='Player',point=200.5,price=110)])])])


def test_quotes_keep_provider_time_and_require_identity_and_start():
    data = event()
    quote, = parse_event_quotes(data,'nfl')
    assert quote.snapped_at == datetime(2026,9,10,15,tzinfo=timezone.utc)
    assert quote.game_start_time == datetime(2026,9,13,17,tzinfo=timezone.utc)
    assert quote.source_provider == 'the_odds_api'
    assert len(quote.source_sha256) == 64
    assert quote.source_record_sha256 == prop_quote_record_sha256(quote)
    assert parse_event_quotes(deepcopy(data),'nfl')[0].source_sha256 == quote.source_sha256
    changed = deepcopy(data)
    changed['bookmakers'][0]['markets'][0]['outcomes'][0]['price'] = 120
    changed_quote, = parse_event_quotes(changed,'nfl')
    assert changed_quote.source_sha256 != quote.source_sha256
    assert changed_quote.source_record_sha256 != quote.source_record_sha256
    for key in ('id','commence_time'):
        invalid = deepcopy(data)
        del invalid[key]
        assert parse_event_quotes(invalid,'nfl') == []
    del data['bookmakers'][0]['markets'][0]['last_update']
    assert parse_event_quotes(data,'nfl') == []
    data = event()
    data['bookmakers'][0]['key'] = 'prizepicks'
    assert parse_event_quotes(data,'nfl') == []


def test_prizepicks_tiers_do_not_create_prices_or_synthetic_games():
    data = dict(included=[dict(type='new_player',id='p',attributes={'name':'Player'})],
        data=[dict(id='projection', attributes=dict(stat_type='Pass Yards',line_score=200.5,
            start_time='2026-09-13T17:00:00Z',odds_type='demon'),
            relationships={'new_player':{'data':{'id':'p'}}})])
    projections, skipped = parse_projections(data)
    assert skipped == 0 and len(projections) == 1
    assert projections[0]['game_id'] is None
    assert projections[0]['tier'] == 'demon'
    assert not {'price','american_odds','implied_probability','payout'} & projections[0].keys()
    data['data'].append(deepcopy(data['data'][0]))
    with pytest.raises(ValueError, match='Duplicate'):
        parse_projections(data)


@pytest.mark.asyncio
async def test_blocked_projection_source_does_not_create_evidence(monkeypatch, tmp_path):
    import httpx
    from sportsbet.ingestion import prizepicks
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    monkeypatch.setattr(prizepicks.httpx, 'AsyncClient', lambda **kwargs: client)
    output = tmp_path / 'capture.json'
    with pytest.raises(RuntimeError, match='HTTP 403'):
        await prizepicks.capture('nfl', output)
    assert not output.exists()
