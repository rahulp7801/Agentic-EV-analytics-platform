from datetime import datetime, timedelta, timezone
from copy import deepcopy
from sportsbet.player_profiles import profile
from sportsbet.player_profiles import run
import pytest


def context():
    now=datetime.now(timezone.utc)
    return now,dict(status='observed',captured_at=now.isoformat(),source_url='injuries',source_sha256='a'*64,teams=[dict(abbreviation='BUF',
        roster_names=['Player'],roster_ids={'123':'Player'},roster_statuses={'Player':'Active'},
        reports=[dict(player='Teammate',status='Out',position='WR',reported_at=now.isoformat())],
        injury_coverage='observed',injury_source_url='injuries',injury_source_sha256='a'*64,
        roster_source_url='roster',roster_source_sha256='b'*64,
        portraits={'Player':dict(player_id='123',player_image_url='portrait',jersey='0',position='QB')})])


def test_profile_is_presentation_only_even_when_teammates_gate_forecast():
    now,data=context(); before=deepcopy(data)
    result=profile(data,'Player',None,now)
    assert result['jersey']=='0' and result['position']=='QB'
    assert result['source_sha256']=='b'*64 and result['name']=='Player'
    assert not {'true_prob','gated','subject_status','teammates'} & result.keys()
    assert data==before
    assert profile(data,'Other',None,now) is None
    assert profile(data,'Player',None,now+timedelta(hours=2)) is None


def test_alias_requires_captured_crosswalk_and_uses_canonical_roster_profile():
    now,data=context()
    data.update(player_identities={'00-0037248':'123'},identity_source=dict(
        url='https://github.com/nflverse/nflverse-data/releases/download/players/players.csv',
        source_sha256='c'*64,retrieved_at=now.isoformat()))
    result=profile(data,'Book Name','00-0037248',now)
    assert result['player']=='Book Name' and result['name']=='Player'
    assert result['identity_source_sha256']=='c'*64
    assert profile(data,'Book Name','00-0000000',now) is None


@pytest.mark.asyncio
async def test_scheduled_profile_refresh_uses_recorded_slate_without_new_quotes(monkeypatch):
    now,data=context(); publications=[]; events=[]
    class Connection:
        async def fetch(self,sql,*args):
            if 'dashboard_snapshots' in sql:
                assert args==('signals:nfl:%',)
                return [dict(payload=dict(signals=[dict(player='Player',game_id='game',home_team='Home',away_team='Away')]))]
            assert args==('Player',)
            return [dict(player_id='00-0037248')]
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    class Pool:
        closed=False
        def acquire(self): return Connection()
        async def close(self): self.closed=True
    pool=Pool()
    async def create_pool(): return pool
    async def collect(event,sport,**kwargs):
        events.append(event);assert sport=='nfl' and kwargs['player_names']=={'Player'}
        return data
    monkeypatch.setattr('sportsbet.player_profiles.create_async_pool',create_pool)
    monkeypatch.setattr('sportsbet.player_profiles.fetch_event_availability',collect)
    monkeypatch.setattr('sportsbet.player_profiles.publish_snapshot',lambda *args:publications.append(args))
    assert (await run(['nfl']))['nfl']==dict(profiles=1,unavailable=0)
    assert events==[dict(id='game',home_team='Home',away_team='Away')]
    assert publications[0][0]=='player-profiles:nfl'
    assert publications[0][1]['profiles'][0]['jersey']=='0' and pool.closed
    publications.clear();data['status']='unavailable'
    assert (await run(['nfl']))['nfl']==dict(profiles=0,unavailable=1)
    assert publications==[]  # Provider failure cannot overwrite the last capture.
