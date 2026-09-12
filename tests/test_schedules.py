from datetime import datetime, timezone
import httpx
import pytest
from sportsbet import schedules


def board():
    return {'events':[{'id':'event','date':'2026-09-11T23:00:00Z','status':{'type':{'completed':True}},'competitions':[{'competitors':[
        {'homeAway':'home','team':{'abbreviation':'H','displayName':'Home'}},
        {'homeAway':'away','team':{'abbreviation':'A','displayName':'Away'}}]}]}]}


def test_schedule_preserves_start_and_rejects_ambiguous_identity():
    rows=schedules.parse_day(board(),'20260911','Today')
    assert len(rows)==1 and rows[0]['game_time']=='2026-09-11T23:00:00+00:00'
    assert rows[0]['completed'] is True
    assert schedules.parse_day(board(),'20260912','Tomorrow')==[]
    data=board();data['events']*=2
    with pytest.raises(ValueError,match='Duplicate'):
        schedules.parse_day(data,'20260911','Today')
    data=board();data['events'][0]['date']='2026-09-11T23:00:00'
    with pytest.raises(ValueError,match='timezone'):
        schedules.parse_day(data,'20260911','Today')
    data=board();del data['events'][0]['status']
    with pytest.raises(ValueError,match='completion'):
        schedules.parse_day(data,'20260911','Today')


@pytest.mark.asyncio
async def test_schedule_supports_bounded_seven_day_settlement_catchup(monkeypatch):
    client=httpx.AsyncClient
    requested=[]
    def respond(request):
        day=request.url.params['dates'];requested.append(day)
        data=board();data['events'][0]['date']=f'{day[:4]}-{day[4:6]}-{day[6:]}T23:00:00Z'
        return httpx.Response(200,json=data)
    monkeypatch.setattr(schedules.httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(respond),**kwargs))
    result=await schedules.collect('nfl',datetime(2026,9,11,18,tzinfo=timezone.utc),offsets=tuple(range(-7,2)))
    assert requested==['20260904','20260905','20260906','20260907','20260908','20260909','20260910','20260911','20260912']
    assert len(result['games'])==9 and result['games'][0]['label']=='2026-09-04'
    assert result['games'][-3]['label']=='Yesterday' and result['games'][-1]['label']=='Tomorrow'
    assert result['status']=='complete'


@pytest.mark.asyncio
@pytest.mark.parametrize('offsets',[(),(-1,-1),(True,),(-8,),(2,)])
async def test_schedule_rejects_unbounded_or_ambiguous_lookback(offsets):
    with pytest.raises(ValueError,match='offsets'):
        await schedules.collect('nfl',datetime.now(timezone.utc),offsets=offsets)
    with pytest.raises(ValueError,match='timezone'):
        await schedules.collect('nfl',datetime.now().replace(tzinfo=None))


@pytest.mark.asyncio
async def test_schedule_custom_window_is_unavailable_only_when_every_date_fails(monkeypatch):
    client=httpx.AsyncClient
    monkeypatch.setattr(schedules.httpx,'AsyncClient',lambda **kwargs:client(
        transport=httpx.MockTransport(lambda request:httpx.Response(503)),**kwargs))
    result=await schedules.collect('nfl',datetime(2026,9,11,18,tzinfo=timezone.utc),offsets=(-7,-2))
    assert result['status']=='unavailable' and len(result['failures'])==2


@pytest.mark.asyncio
async def test_schedule_partial_failure_retains_available_dates(monkeypatch):
    client=httpx.AsyncClient
    def respond(request):
        if request.url.params['dates']=='20260912':
            return httpx.Response(503)
        return httpx.Response(200,json=board())
    monkeypatch.setattr(schedules.httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(respond),**kwargs))
    result=await schedules.collect('nfl',datetime(2026,9,11,18,tzinfo=timezone.utc))
    assert result['status']=='partial' and len(result['games'])==1
    assert len(result['sources'])==2 and result['failures'][0]['date']=='20260912'
