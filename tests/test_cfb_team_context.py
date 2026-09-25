from datetime import date, timedelta
import copy

import pytest

from sportsbet.ingestion.provenance import stat_row_sha256
from sportsbet.quant.cfb_team_context import audit_rows, candidate_examples, team_estimate


def rows():
    return [dict(player='1', game=str(i+1), season=2024 if i<25 else 2025,
        day=date(2024,1,1)+timedelta(days=7*i) if i<25 else date(2025,9,1)+timedelta(days=7*(i-25)),
        team='A' if i<28 else 'B', passing_yards=100+i%10, rushing_yards=i%10,
        receiving_yards=i%10, receptions=i%4) for i in range(40)]


def test_same_team_reproduces_baseline_and_return_to_old_team_starts_new_segment():
    history=[dict(r,team='A') for r in rows()[:20]]
    original=team_estimate(history,'receiving_yards',4.5)
    assert original['probability']==original['baseline']
    assert original['current_segment_games']==20
    history[18]['team']='B'
    result=team_estimate(history,'receiving_yards',4.5)
    older=(sum(r['receiving_yards']>4.5 for r in history[:19])+.5)/20
    assert result['current_segment_games']==1 and result['older_segment_games']==19
    assert result['probability']==pytest.approx((1+20*older)/21)


def test_target_team_outcome_and_future_cannot_change_current_prediction():
    history=rows();target=history[32]
    before=copy.deepcopy(history)
    examples,probabilities,contexts,_=candidate_examples(history,'rec_yds')
    changed=[dict(r,team='FUTURE',receiving_yards=999) if r['day']>=target['day'] else r for r in history]
    replay,p2,c2,_=candidate_examples(changed,'rec_yds')
    first=[(e.line,e.base,p,context) for e,p,context in zip(examples,probabilities,contexts) if e.day==target['day']]
    second=[(e.line,e.base,p,context) for e,p,context in zip(replay,p2,c2) if e.day==target['day']]
    assert first and first==second
    assert history==before
    assert any(e.outcome==0 for e in examples if e.day==target['day'])
    assert all(e.outcome==1 for e in replay if e.day==target['day'])


def test_missing_categories_same_day_and_season_floor_match_existing_research():
    history=rows();target=history[30]
    history[0]['receiving_yards']=None
    history[1]['season']=2020
    history[29]['day']=target['day']
    examples,_,_,_=candidate_examples(history,'rec_yds')
    assert {e.sample for e in examples if e.day==target['day']}=={27}
    history.append(dict(history[-1]))
    with pytest.raises(ValueError,match='Duplicate'):candidate_examples(history,'rec_yds')


@pytest.mark.parametrize('fault',['missing_team','missing_category','boolean','nan','reordered','duplicate','short','integer_line'])
def test_invalid_context_cannot_fall_back_to_invented_values(fault):
    history=rows()[:20];line=4.5
    if fault=='missing_team':history[0]['team']=''
    elif fault=='missing_category':history[0]['receiving_yards']=None
    elif fault=='boolean':history[0]['receiving_yards']=True
    elif fault=='nan':history[0]['receiving_yards']=float('nan')
    elif fault=='reordered':history.reverse()
    elif fault=='duplicate':history[0]=history[1]
    elif fault=='short':history.pop()
    else:line=4
    with pytest.raises(ValueError):team_estimate(history,'receiving_yards',line)


def committed_row():
    row=dict(game_id='123',athlete_id=1,player_name='Player',team_id=1,
        season=2024,week=1,game_date=date(2024,9,1),is_home=True,
        team_name='Home',team_abbreviation='HOM',opponent_id=2,
        opponent_name='Away',opponent_abbreviation='AWY',passing_yards=None,
        rushing_yards=10,receiving_yards=5,receptions=1)
    return row|dict(player='1',game='123',day=row['game_date'],team='HOM',
        source_provider='sportsdataverse_espn',source_sha256='a'*64,
        source_record_sha256=stat_row_sha256('cfb',row|{'game_id':123}))


def test_source_and_alias_bindings_are_checked_and_empty_cohorts_never_promote():
    row=committed_row();result=audit_rows([row])
    assert result['promote'] is False
    assert all(r['partitions']['evaluate']['all']['comparison'] is None for r in result['markets'].values())
    for patch in [{'rushing_yards':20},{'team':'OTHER'},{'player':'2'},
                  {'day':date(2024,9,2)},{'game':'999'},{'source_sha256':'bad'},
                  {'source_provider':'invented'}]:
        with pytest.raises(ValueError,match='source'):audit_rows([row|patch])
