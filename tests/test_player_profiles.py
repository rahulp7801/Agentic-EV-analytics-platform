from datetime import datetime, timedelta, timezone
from copy import deepcopy
from sportsbet.player_profiles import profile


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
