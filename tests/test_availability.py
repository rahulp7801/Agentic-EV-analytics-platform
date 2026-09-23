from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from sportsbet.prop.availability import (blocks_unadjusted_teammate_context,
                                         fetch_event_availability, player_availability)


def context():
    return dict(status='observed',captured_at=datetime.now(timezone.utc).isoformat(),
                source_url='https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries',
                source_sha256='a'*64,teams=[dict(abbreviation='KC',roster_names=['Player','Teammate'],reports=[],
                    roster_statuses={'Player':'Active','Teammate':'Active'},roster_source_url='roster',roster_source_sha256='b'*64)])


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
    data=context();data['teams'][0]['roster_statuses']['Player']='Inactive'
    assert player_availability(data,'Player',now)[1]=='player_availability_risk'
    data=context();data['status']='partial'
    data['teams'].append(dict(abbreviation='OTHER',roster_names=['Opponent'],injury_coverage='unavailable'))
    assert player_availability(data,'Player',now)[1] is None
    assert player_availability(data,'Opponent',now)[1]=='availability_unavailable'


def test_only_confirmed_acute_teammate_absences_block_the_baseline():
    assert blocks_unadjusted_teammate_context({'status':'Out'})
    assert blocks_unadjusted_teammate_context({'status':'Inactive','relationship':'teammate'})
    assert blocks_unadjusted_teammate_context({'status':'Doubtful','relationship':'teammate'})
    assert not blocks_unadjusted_teammate_context({'status':'Questionable','relationship':'teammate'})
    assert not blocks_unadjusted_teammate_context({'status':'Injured Reserve','relationship':'teammate'})
    assert not blocks_unadjusted_teammate_context({'status':'Out','relationship':'opponent'})


@pytest.mark.parametrize('sport,missing_team',[('nfl',False),('nba',False),('nba',True),('cfb',False),('cfb',True)])
async def test_exact_team_rosters_and_archived_response_hashes(sport,missing_team,tmp_path,monkeypatch):
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
            body['injuries']=[dict(id=t['id'],displayName=t['displayName'],injuries=[]) for t in (teams[:1] if missing_team else teams)]
        else:
            identity=request.url.path.split('/')[-2]
            body['team']=dict(id=identity)
            image_sport='college-football' if sport=='cfb' else sport
            athletes=[dict(id='123',headshot={'href':f'https://a.espncdn.com/i/headshots/{image_sport}/players/full/123.png'},displayName='Player' if identity=='1' else 'Opponent',status={'name':'Active'})]
            body['athletes']=[dict(items=athletes)] if sport in ('nfl','cfb') else athletes
        return httpx.Response(200,json=body)
    original=httpx.AsyncClient
    with patch('sportsbet.prop.availability.httpx.AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle))):
        result=await fetch_event_availability(dict(id='event',home_team='Home',away_team='Away'),sport)
        assert result['status']==('partial' if missing_team else 'observed') and len(result['source_sha256'])==64
        assert player_availability(result,'Player',datetime.now(timezone.utc))[0]['team']=='Home'
        image_sport='college-football' if sport=='cfb' else sport
        assert player_availability(result,'Player',datetime.now(timezone.utc))[0]['player_image_url']==f'https://a.espncdn.com/i/headshots/{image_sport}/players/full/123.png'
        assert player_availability(result,'Opponent',datetime.now(timezone.utc))[0]['status']==('unavailable' if missing_team else 'observed')
        assert len(list((tmp_path/'.local/availability').glob('*.json')))==1
        result=await fetch_event_availability(dict(id='event',home_team='Wrong',away_team='Away'),sport)
        assert result['status']=='unavailable'
    assert len(requests)==6
    directories=[url for url in requests if url.split('?')[0].endswith('/teams')]
    assert len(directories)==2
    assert all(('limit=1000' in url)==(sport=='cfb') for url in directories)


async def test_provider_denial_is_unknown_not_empty_healthy_report():
    original=httpx.AsyncClient
    with patch('sportsbet.prop.availability.httpx.AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(lambda r:httpx.Response(403)))):
        result=await fetch_event_availability(dict(id='event',home_team='Home',away_team='Away'),'nfl')
    assert result['status']=='unavailable'


@pytest.mark.parametrize('sport', ['nfl', 'nba'])
@pytest.mark.parametrize('league_mode', ['omitted', 'denied', 'observed'])
async def test_roster_injuries_cover_omitted_reports_without_inventing_healthy_lineup(
    sport, league_mode, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    teams = [dict(id=str(i), displayName=name, abbreviation=name)
             for i, name in enumerate(['Home', 'Away'], 1)]
    def handle(request):
        body = dict(status='success', timestamp=now)
        if request.url.path.endswith('/teams'):
            body['sports'] = [dict(leagues=[dict(teams=[dict(team=t) for t in teams])])]
        elif request.url.path.endswith('/injuries'):
            if league_mode=='denied':
                return httpx.Response(403)
            body['injuries'] = [dict(id=t['id'], displayName=t['displayName'], injuries=[])
                               for t in teams] if league_mode=='observed' else []
        else:
            identity = request.url.path.split('/')[-2]
            body['team'] = dict(id=identity)
            athletes = [dict(displayName='Player' if identity=='1' else 'Opponent',
                position={'abbreviation':'QB' if sport=='nfl' else 'PG'},
                status={'name':'Active'}, injuries=[])]
            if identity=='1':
                athletes.append(dict(displayName='Teammate', position={'abbreviation':'RB'},
                    status={'name':'Active'}, injuries=[dict(status='Questionable', date=now)]))
            body['athletes'] = [dict(items=athletes)] if sport=='nfl' else athletes
        return httpx.Response(200, json=body)
    original = httpx.AsyncClient
    with patch('sportsbet.prop.availability.httpx.AsyncClient',
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle))):
        result = await fetch_event_availability(dict(id='event', home_team='Home', away_team='Away'), sport)
    assert result['status']=='observed'
    evidence, reason = player_availability(result, 'Player', datetime.now(timezone.utc))
    assert reason is None  # Questionable is disclosed context, not a confirmed absence.
    if league_mode!='observed':
        assert evidence['source_url']==evidence['roster_source_url']
        assert evidence['source_sha256']==evidence['roster_source_sha256']
    assert evidence['teammates'][0]['status']=='Questionable'
    assert evidence['probability_adjusted'] is False
    assert player_availability(result, 'Teammate', datetime.now(timezone.utc))[1]=='player_availability_risk'
    opponent, reason = player_availability(result, 'Opponent', datetime.now(timezone.utc))
    assert reason is None and opponent['subject_status']=='Not listed on injury report'
    assert len(list((tmp_path/'.local/availability').glob('*.json')))==1


@pytest.mark.parametrize('defect', ['missing_array','null_array','future_date','naive_date','duplicate','conflict','stale','wrong_team'])
async def test_roster_fallback_rejects_incomplete_or_conflicting_evidence(defect, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc)
    def handle(request):
        body = dict(status='success', timestamp=now.isoformat())
        if request.url.path.endswith('/teams'):
            body['sports'] = [dict(leagues=[dict(teams=[dict(team=dict(id=str(i), displayName=name,
                abbreviation=name)) for i,name in enumerate(['Home','Away'],1)])])]
        elif request.url.path.endswith('/injuries'):
            body['injuries'] = [] if defect!='conflict' else [dict(id='1', displayName='Home', injuries=[
                dict(status='Active', date=now.isoformat(), athlete=dict(displayName='Player',
                    team={'id':'1'}, position={'abbreviation':'QB'}))])]
        else:
            identity = request.url.path.split('/')[-2]
            body['team'] = dict(id='9' if defect=='wrong_team' else identity)
            report = dict(status='Out', date=(now+timedelta(minutes=1)).isoformat() if defect=='future_date'
                else now.replace(tzinfo=None).isoformat() if defect=='naive_date' else now.isoformat())
            athlete = dict(displayName='Player' if identity=='1' else 'Opponent', position={'abbreviation':'QB'},
                status={'name':'Active'}, injuries=[report,report] if defect=='duplicate' else [report])
            if defect=='missing_array':
                del athlete['injuries']
            if defect=='null_array':
                athlete['injuries']=None
            if defect=='stale':
                body['timestamp']=(now-timedelta(hours=2)).isoformat()
            body['athletes']=[dict(items=[athlete])]
        return httpx.Response(200,json=body)
    original=httpx.AsyncClient
    with patch('sportsbet.prop.availability.httpx.AsyncClient',
        lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle))):
        result=await fetch_event_availability(dict(id='event',home_team='Home',away_team='Away'),'nfl')
    assert result['status'] in ('partial','unavailable')
    assert player_availability(result,'Player',now)[1]=='availability_unavailable'
