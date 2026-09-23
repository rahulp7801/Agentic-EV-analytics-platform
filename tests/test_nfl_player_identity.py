import hashlib
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pytest

from sportsbet.prop.availability import NFL_PLAYER_IDS_URL, fetch_event_availability, player_availability


@pytest.mark.parametrize('defect', [None, 'duplicate_gsis', 'duplicate_espn', 'missing_columns', 'evil_redirect', 'http_redirect', 'credential_redirect', 'malformed_redirect', 'denied','not_requested','exact_requested'])
async def test_crosswalk_binds_exact_player_ids_and_unknown_identity_never_borrows_history(defect,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    now=datetime.now(timezone.utc)
    csv='gsis_id,espn_id,pfr_id\n00-0037248,4379399,CookJa01\n'
    if defect=='duplicate_gsis':csv+='00-0037248,123,Other00\n'
    if defect=='duplicate_espn':csv+='00-0000001,4379399,Other00\n'
    if defect=='missing_columns':csv='name,id\nJames Cook,4379399\n'
    requests=[]
    def handle(request):
        requests.append(str(request.url))
        if request.url.host=='github.com':
            redirects={'evil_redirect':'https://evil.example/players.csv','http_redirect':'http://github.com/players.csv',
                'credential_redirect':'https://user:password@github.com/players.csv','malformed_redirect':'https://['}
            if defect in redirects:return httpx.Response(302,headers={'Location':redirects[defect]})
            if defect=='denied':return httpx.Response(403)
            return httpx.Response(200,content=csv.encode())
        body=dict(status='success',timestamp=now.isoformat())
        teams=[dict(id=str(i),displayName=name,abbreviation=name) for i,name in enumerate(['Home','Away'],1)]
        if request.url.path.endswith('/teams'):
            body['sports']=[dict(leagues=[dict(teams=[dict(team=t) for t in teams])])]
        elif request.url.path.endswith('/injuries'):body['injuries']=[]
        else:
            identity=request.url.path.split('/')[-2]
            body['team']={'id':identity}
            body['athletes']=[dict(items=[dict(id='4379399' if identity=='1' else '123',
                displayName='James Cook III' if identity=='1' else 'Opponent',status={'name':'Active'},
                position={'abbreviation':'RB'},injuries=[])])]
        return httpx.Response(200,json=body)
    original=httpx.AsyncClient
    with patch('sportsbet.prop.availability.httpx.AsyncClient',
        lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle))):
        result=await fetch_event_availability(dict(id='event',home_team='Home',away_team='Away'),'nfl',
            player_names=None if defect=='not_requested' else {'James Cook III' if defect=='exact_requested' else 'James Cook'})
    assert result['status']=='observed'
    evidence,reason=player_availability(result,'James Cook',now,player_id='00-0037248')
    if defect and defect!='exact_requested':
        assert reason=='roster_unconfirmed' and evidence['status']=='unavailable'
        assert all(httpx.URL(url).host in ('github.com','site.api.espn.com') for url in requests)
        if defect=='not_requested':assert not any(httpx.URL(url).host=='github.com' for url in requests)
    else:
        assert reason is None and evidence['roster_player_name']=='James Cook III'
        assert evidence['identity_source_url']==NFL_PLAYER_IDS_URL
        assert evidence['identity_source_sha256']==hashlib.sha256(csv.encode()).hexdigest()
        assert result['pfr_player_identities']=={'4379399':'CookJa01'}
        assert evidence['probability_adjusted'] is False
        assert 'response_text' not in result['identity_source']
        assert player_availability(result,'James Cook',now,player_id='00-0000001')[1]=='roster_unconfirmed'
        assert player_availability(result,'James Cook',now)[1]=='roster_unconfirmed'
        exact,exact_reason=player_availability(result,'Opponent',now,player_id='00-0000001')
        assert exact_reason is None and exact['status']=='observed' and 'roster_player_name' not in exact
        result['teams'][0]['reports']=[dict(player='James Cook III',status='Out',position='RB',reported_at=now.isoformat())]
        assert player_availability(result,'James Cook',now,player_id='00-0037248')[1]=='player_availability_risk'
