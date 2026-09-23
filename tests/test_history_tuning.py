from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from sportsbet.quant.history_tuning import (
    BASE, Example, build_examples, compare, evaluate_examples, fit_correction,
    game_weights, partition, score, source_summary,
)


def histories():
    return [dict(player='player', game=f'g{i}', day=date(2024, 10, 22)+timedelta(days=2*i),
                 season=2024, team='B' if i>=25 else 'A', points=10+i%9,
                 minutes=20+i%5, source_record_sha256=None) for i in range(45)]


def test_target_outcome_workload_team_and_future_rows_never_enter_features():
    rows=histories()
    original,_=build_examples(rows,'nba','points')
    target=rows[36]
    changed=[dict(row,points=999,minutes=0,team='FUTURE') if row['day']>=target['day'] else row
             for row in rows]
    replay,_=build_examples(changed,'nba','points')
    before=[e for e in original if e.day==target['day']]
    after=[e for e in replay if e.day==target['day']]
    assert before and len(before)==len(after)
    assert [(e.line,e.features,e.base,e.sample) for e in before]==[(e.line,e.features,e.base,e.sample) for e in after]
    assert all(e.outcome==1 for e in after)
    assert any(e.outcome==0 for e in before)


def test_same_day_records_are_excluded_and_missing_stats_are_not_zeroes():
    rows=histories()[:22]
    rows[19]['day']=rows[20]['day']
    rows[2]['points']=None
    examples,coverage=build_examples(rows,'nba','points')
    assert not [e for e in examples if e.day==rows[20]['day']]
    assert coverage['excluded']['fit:fewer_than20']>0
    assert all(e.sample==20 for e in examples)
    rows.append(dict(rows[-1]))
    with pytest.raises(ValueError,match='Duplicate'):
        build_examples(rows,'nba','points')


def test_prior_workload_relevance_and_season_floor():
    rows=histories()
    for row in rows[:25]:row['minutes']=0
    examples,coverage=build_examples(rows,'nba','points')
    assert coverage['excluded']['fit:low_prior_workload']>0
    assert min(e.day for e in examples)>rows[25]['day']
    for row in rows[:30]:row['season']=2021
    examples,_=build_examples(rows,'nba','points')
    assert not examples


def example(i,split='fit',outcome=None):
    p=.3+.1*(i%4)
    return Example(split,f'g{i//10}',f'p{i%10}',date(2025,1,1),i+.5,
                   int(i%3==0) if outcome is None else outcome,p,.45,.4,
                   (i%4/3,i%3/2,0,0,0,2,0),30,False)


def test_duplicate_alternate_thresholds_cannot_overweight_player_or_game():
    a=example(0)
    b=replace(example(1),base=.8)
    c=replace(example(2),game='other')
    rows=[a,replace(a,line=10.5),b,c]
    assert game_weights(rows)==pytest.approx([.25,.25,.5,1])
    duplicate=rows+[replace(a,line=20.5)]
    for cohort in (rows,duplicate):
        result=score(cohort,np.asarray([e.base for e in cohort]))
        assert result['game_balanced_brier']==pytest.approx(
            (((a.base-a.outcome)**2+(b.base-b.outcome)**2)/2+(c.base-c.outcome)**2)/2)


def test_selection_and_fitted_scaling_do_not_use_evaluation_outcomes():
    rows=[replace(example(i),game=f'{split}-{i//10}',split=split)
          for split in ('fit','select','evaluate') for i in range(120)]
    first=evaluate_examples(rows)
    changed=[replace(e,outcome=1-e.outcome) if e.split=='evaluate' else e for e in rows]
    second=evaluate_examples(changed)
    assert first['selected']==second['selected']
    assert first['selection_scores']==second['selection_scores']
    assert first['fitted_corrections']==second['fitted_corrections']
    assert first['promote'] is second['promote'] is False


def test_insufficient_splits_never_rank_or_promote_a_model():
    result=evaluate_examples([example(i) for i in range(20)])
    assert result['status']=='insufficient_data' and result['promote'] is False
    assert 'selected' not in result


def test_fitted_predictions_finite_and_cluster_differences_consistent():
    rows=[example(i) for i in range(120)]
    fitted=fit_correction(rows,.1)
    predictions=fitted.predict(rows)
    assert np.isfinite(predictions).all() and ((predictions>0)&(predictions<1)).all()
    same=compare(rows,predictions,predictions)
    assert all(value==0 or value==[0,0] for value in same.values())
    result=score(rows,predictions)
    assert result['games']==12 and result['players']==10


def test_temporal_partitions_and_legacy_provenance_are_explicit():
    assert partition('nba',date(2025,12,31),2025)=='select'
    assert partition('nba',date(2026,1,1),2025)=='evaluate'
    assert partition('nfl',date(2026,1,1),2025)=='evaluate'
    assert partition('cfb',date(2026,9,23),2026) is None
    rows=[dict(histories()[0],rebounds=2,assists=1)]
    result=source_summary(rows,'nba')
    assert result['provenance']=={'missing_row_commitment':1}
    assert result['workload_fields_covered_by_stat_commitment'] is False


def test_cfb_provenance_normalizes_stored_numeric_event_identity():
    from sportsbet.ingestion.provenance import stat_row_sha256
    raw=dict(game_id=123,athlete_id=456,player_name='Player',team_id=1,
        passing_yards=None,rushing_yards=1,receiving_yards=12,receptions=2,
        season=2025,week=1,game_date=date(2025,9,1),is_home=True,team_name='Home',
        team_abbreviation='H',opponent_id=2,opponent_name='Away',opponent_abbreviation='A')
    digest=stat_row_sha256('cfb',raw)
    stored=raw|{'game_id':'123','source_record_sha256':digest}
    assert source_summary([stored],'cfb')['provenance']=={'verified_core_stat_commitment':1}
    stored['receiving_yards']=99
    assert source_summary([stored],'cfb')['provenance']=={'mismatched_core_stat_commitment':1}
