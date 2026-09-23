import copy
from datetime import datetime,timezone
import hashlib

import pytest

from sportsbet.ingestion.provenance import row_sha256,stat_row_sha256
from sportsbet.quant.nfl_history_coverage import audit,IDENTITY_URL

NOW=datetime(2026,9,23,tzinfo=timezone.utc)
GSIS='00-0036422';PFR='TrauAd00'


def item(week,kind,*,season=2026,day=None):
    day=day or ('2026-09-13' if week==1 else '2026-09-20')
    game=f'{season}_{week:02}_JAX_DEN'
    if kind=='stat':
        row=dict(player_id=GSIS,season=season,week=week,team='DEN',passing_yards=0,rushing_yards=0,receiving_yards=10,receptions=1)
        digest=stat_row_sha256('nfl',row)
    else:
        row=dict(game_id=game,season=season,week=week,player_name='Player',pfr_player_id=PFR,position='TE',team='DEN',opponent='JAX',offense_snaps=20,defense_snaps=0)
        digest=row_sha256(row)
    row.update(source_provider='nflverse',source_sha256='a'*64,source_record_sha256=digest,source_observed_at=NOW.isoformat())
    return dict(game_id=game,game_date=day,home_team='DEN',away_team='JAX',**{kind:row})


def fixture():
    csv=f'gsis_id,pfr_id\n{GSIS},{PFR}\n'
    return dict(observed_at=NOW.isoformat(),cutoff='2026-09-24',season_floor=2024,
        identity=dict(url=IDENTITY_URL,retrieved_at=NOW.isoformat(),response_text=csv,source_sha256=hashlib.sha256(csv.encode()).hexdigest()),
        players=[dict(player_id=GSIS,pfr_player_id=PFR,player='Player',current_quoted=True)],
        stats=[item(1,'stat')],snaps=[item(1,'snap'),item(2,'snap')])


def test_missing_played_game_stays_unknown_and_inputs_stay_unchanged():
    data=fixture();before=copy.deepcopy(data);report=audit(data,now=NOW)
    assert data==before
    assert report['missing_stat_games']==1 and report['verified_offensive_rows']==2
    assert report['current_quoted_players_with_missing']==1
    assert report['missing_games'][0]['outcome']=='unknown'
    coverage=report['player_coverage'][0]
    assert coverage['union_last40_known']==coverage['union_last40_unknown']==1
    assert coverage['missing_inside_recorded_span']==1
    assert report['invented_stat_rows']==report['published_forecasts']==0


def test_exclusive_cutoff_does_not_count_later_participation():
    data=fixture();data['cutoff']='2026-09-20'
    report=audit(data,now=NOW)
    assert report['missing_stat_games']==0
    assert report['excluded']=={'snaps_outside_cutoff':1}


def test_zero_offensive_snaps_do_not_establish_missing_played_game():
    data=fixture();row=data['snaps'][1]['snap'];row['offense_snaps']=0
    row['source_record_sha256']=row_sha256({k:v for k,v in row.items() if not k.startswith('source_')})
    report=audit(data,now=NOW)
    assert report['missing_stat_games']==0 and report['excluded']['zero_offense_snaps']==1


@pytest.mark.parametrize('mutation',['bad_stat_hash','bad_snap_hash','future_source','duplicate_stat','duplicate_snap','wrong_game','wrong_team','wrong_opponent','wrong_binding','duplicate_binding'])
def test_invalid_evidence_never_becomes_a_missing_result(mutation):
    data=fixture()
    if mutation=='bad_stat_hash':data['stats'][0]['stat']['source_record_sha256']='0'*64
    if mutation=='bad_snap_hash':data['snaps'][0]['snap']['source_record_sha256']='0'*64
    if mutation=='future_source':data['snaps'][0]['snap']['source_observed_at']='2026-09-24T00:00:00Z'
    if mutation=='duplicate_stat':data['stats'].append(copy.deepcopy(data['stats'][0]))
    if mutation=='duplicate_snap':data['snaps'].append(copy.deepcopy(data['snaps'][0]))
    if mutation=='wrong_game':data['stats'][0]['game_id']='2026_01_JAX_KC'
    if mutation=='wrong_team':data['snaps'][0]['home_team']='KC'
    if mutation=='wrong_opponent':
        row=data['snaps'][0]['snap'];row['opponent']='SEA'
        row['source_record_sha256']=row_sha256({k:v for k,v in row.items() if not k.startswith('source_')})
    if mutation=='wrong_binding':data['players'][0]['pfr_player_id']='Other00'
    if mutation=='duplicate_binding':
        text=data['identity']['response_text']+'00-0000001,'+PFR+'\n'
        data['identity'].update(response_text=text,source_sha256=hashlib.sha256(text.encode()).hexdigest())
    with pytest.raises(ValueError):audit(data,now=NOW)


def test_last40_union_retains_unknowns_and_drops_oldest_records():
    data=fixture();data['stats']=[];data['snaps']=[]
    keys=[(2024,w) for w in range(1,19)]+[(2025,w) for w in range(1,19)]+[(2026,w) for w in range(1,9)]
    for i,(season,week) in enumerate(keys):
        day=f'{season}-09-01'
        data['snaps'].append(item(week,'snap',season=season,day=day))
        if i not in (0,43):data['stats'].append(item(week,'stat',season=season,day=day))
    coverage=audit(data,now=NOW)['player_coverage'][0]
    assert coverage['missing_stat_games']==2
    assert coverage['recorded_last40_count']==40
    assert coverage['missing_inside_recorded_span']==1
    assert coverage['union_last40_count']==40 and coverage['union_last40_unknown']==1
