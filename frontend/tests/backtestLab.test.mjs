import test from 'node:test';
import assert from 'node:assert/strict';
import {formatBacktestMetric, mispricedProps, strategySuggestions} from '../lib/backtestLab.ts';

const report = {
  cohort:'recommendations', sport:'nfl', model_version:'empirical-jeffreys-v4', sample_size:80,
  settled_count:80, decided_count:80, pending_count:0, excluded_missing_metadata:0,
  roi:.08, hit_rate:.58, brier_score:.19, log_loss:.55, calibration_error:.03,
  calibration_count:80, clv_mean:.02, clv_count:80, baseline_50_brier:.25,
  roi_game_cluster_interval:[.01,.15], brier_score_game_cluster_interval:[.16,.22],
  log_loss_game_cluster_interval:[.49,.61], clv_mean_game_cluster_interval:[.005,.035],
};

test('strategy suggestions require multiple supported metrics and a minimum holdout', () => {
  const selected=['roi','brier_score','log_loss','calibration_error','clv_mean'];
  const suggestions=strategySuggestions([report],selected,50);
  assert.equal(suggestions.length,1);
  assert.deepEqual([...suggestions[0].metrics].sort(),[...selected].sort());
  assert.deepEqual(strategySuggestions([{...report,decided_count:20}],selected,50),[]);
  assert.deepEqual(strategySuggestions([{...report,roi_game_cluster_interval:[-.01,.15]}],['roi','hit_rate'],50),[]);
});

test('mispriced props require current eligible recorded evidence', () => {
  const now=Date.parse('2026-09-15T20:00:00Z');
  const signal={id:'one',player:'Player',team:'A',opponent:'B',sport:'nfl',prop_type:'pass_yds',line:250.5,
    direction:'over',true_prob:.6,implied_prob:.52,ev_pct:.08,expected_return:.1,push_probability:0,
    confidence_interval:[.54,.66],game_start_time:'2026-09-15T22:00:00Z',kelly_fraction:.02,
    american_odds:-110,sportsbook:'book',trade_plan:[],injury_flags:{},market_type:'player_pass_yds',
    snapped_at:'2026-09-15T19:58:00Z',strength:'unrated',gated:false,sample_size:40};
  assert.deepEqual(mispricedProps([signal], 'nfl', now).map(item=>item.id),['one']);
  assert.equal(mispricedProps([{...signal,gated:true}], 'nfl', now).length,0);
  assert.equal(mispricedProps([{...signal,snapped_at:'2026-09-15T19:50:00Z'}], 'nfl', now).length,0);
  assert.equal(mispricedProps([{...signal,confidence_interval:null}], 'nfl', now).length,0);
});

test('metric formatting keeps units explicit',()=>{
  assert.equal(formatBacktestMetric('roi',.123),'12.3%');
  assert.equal(formatBacktestMetric('clv_mean',.0123),'1.23pp');
  assert.equal(formatBacktestMetric('brier_score',null),'Unavailable');
});
