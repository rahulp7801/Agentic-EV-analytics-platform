from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from sportsbet.prop.availability import fetch_event_availability, player_availability


def context():
    return dict(status='observed',captured_at=datetime.now(timezone.utc).isoformat(),
                source_url='https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries',
                source_sha256='a'*64,teams=[dict(abbreviation='KC',roster_names=['Player','Teammate'],reports=[])])


def test_availability_never_infers_healthy_or_boosts_probability():
    now=datetime.now(timezone.utc)
    data=context()
    evidence,reason=player_availability(data,'Player',now)
    assert reason is None and evidence['subject_status']=='Not listed on injury report'
    assert evidence['probability_adjusted'] is False
    data['teams'][0]['reports']=[dict(player='Teammate',status='Out',position='WR',reported_at=now.isoformat())]
    evidence,reason=player_availability(data,'Player',now)
    assert reason=='teammate_availability_unmodeled' and evidence['teammates'][0]['status']=='Out'
    assert player_availability(data,'Teammate',now)[1]=='player_availability_risk'
    assert player_availability(data,'Unknown',now)[1]=='roster_unconfirmed'
    data['captured_at']=(now-timedelta(hours=2)).isoformat()
    assert player_availability(data,'Player',now)[1]=='availability_unavailable'
    assert player_availability(None,'Player',now)[1]=='availability_unavailable'


@pytest.mark.parametrize('sport',['nfl','nba'])
async def test_exact_team_rosters_and_archived_response_hashes(sport,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    now=datetime.now(timezone.utc).isoformat()
    teams=[dict(id=str(i),displayName=name,abbreviation=name) for i,name in enumerate(['Home','Away'],1)]
    requests=[]
    def handle(request):
        requests.append(str(request.url))
        body=dict(status='success',timestamp=now)
        if request.url.path.endswith('/teams'):
            body['sports']=[dict(leagues=[dict(teams=[dict(team=t) for t in teams])])]
        elif request.url.path.endswith('/injuries'):
            body['injuries']=[dict(id=t['id'],displayName=t['displayName'],injuries=[]) for t in teams]
        else:
            identity=request.url.path.split('/')[-2]
            body['team']=dict(id=identity)
            athletes=[dict(displayName='Player' if identity=='1' else 'Opponent')]
            body['athletes']=[dict(items=athletes)] if sport=='nfl' else athletes
        return httpx.Response(200,json=body)
    original=httpx.AsyncClient
    with patch('sportsbet.prop.availability.httpx.AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle))):
        result=await fetch_event_availability(dict(id='event',home_team='Home',away_team='Away'),sport)
        assert result['status']=='observed' and len(result['source_sha256'])==64
        assert player_availability(result,'Player',datetime.now(timezone.utc))[0]['team']=='Home'
        assert len(list((tmp_path/'.local/availability').glob('*.json')))==1
        result=await fetch_event_availability(dict(id='event',home_team='Wrong',away_team='Away'),sport)
        assert result['status']=='unavailable'
    assert len(requests)==6


async def test_provider_denial_is_unknown_not_empty_healthy_report():
    original=httpx.AsyncClient
    with patch('sportsbet.prop.availability.httpx.AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(lambda r:httpx.Response(403)))):
        result=await fetch_event_availability(dict(id='event',home_team='Home',away_team='Away'),'nfl')
    assert result['status']=='unavailable'
