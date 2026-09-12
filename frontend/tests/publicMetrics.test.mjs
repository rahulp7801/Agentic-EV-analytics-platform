import assert from 'node:assert/strict';
import test from 'node:test';

import { publicMetrics } from '../lib/publicMetrics.ts';

function report() {
  return {cohort:'all_predictions',model_version:'empirical-jeffreys-v3',
    available_model_versions:['empirical-jeffreys-v3'],sample_size:4,settled_count:3,
    decided_count:2,pending_count:0,void_count:1,excluded_missing_metadata:2,
    duplicate_predictions:1,excluded_closing_quotes:1,unverified_settlements:1,
    roi:0.1,hit_rate:0.5,hit_rate_interval:[0.1,0.9],clv_mean:0.02,clv_count:2,
    calibration_count:2,calibration_positive_count:1,brier_score:0.2,log_loss:0.5,
    calibration_error:0.1,baseline_zero_brier:0.5,baseline_50_brier:0.25,
    baseline_one_brier:0.5,calibration:[{lower:0.5,upper:0.6,count:2,predicted:0.55,
      observed:0.5,observed_interval:[0.1,0.9]}],roi_game_cluster_interval:[-0.2,0.4],
    roi_game_cluster_count:2,hit_rate_game_cluster_interval:[0,1],
    hit_rate_game_cluster_count:2,brier_score_game_cluster_interval:[0.1,0.3],
    log_loss_game_cluster_interval:[0.3,0.7],calibration_game_cluster_count:2,
    clv_mean_game_cluster_interval:[-0.01,0.05],clv_game_cluster_count:2,
    binomial_interval_method:'untrusted',game_cluster_interval_method:'untrusted',
    closing_line_note:'untrusted',selection_policy:'untrusted',profit_scope:'untrusted',
    database_url:'internal',signals_df:[{internal:true}]};
}

test('public metrics validates relationships and strips internal or mutable text', () => {
  const result=publicMetrics(report(),'all');
  assert.equal(result.cohort,'all_predictions');
  assert.equal(result.roi_game_cluster_count,2);
  assert.match(result.profit_scope,/not executed bets/);
  assert.equal('database_url' in result,false);
  assert.equal('signals_df' in result,false);
  assert.equal(JSON.stringify(result).includes('untrusted'),false);
});

test('public metrics accepts the pre-cluster empty snapshot during rollout', () => {
  const value=report();
  Object.assign(value,{model_version:null,available_model_versions:[],sample_size:0,settled_count:0,
    decided_count:0,pending_count:0,void_count:0,roi:null,hit_rate:null,
    clv_mean:null,clv_count:0,calibration_count:0,calibration_positive_count:0,brier_score:null,
    log_loss:null,baseline_zero_brier:null,baseline_50_brier:null,
    baseline_one_brier:null,calibration:[]});
  delete value.hit_rate_interval;delete value.calibration_error;
  for (const key of Object.keys(value)) if (key.includes('game_cluster')) delete value[key];
  const result=publicMetrics(value,'all');
  assert.equal(result.sample_size,0);
  assert.equal('roi_game_cluster_interval' in result,false);
});

test('public metrics fails closed on malformed counts, bounds, cohorts and partial clusters', () => {
  for (const mutate of [
    value => { value.cohort='recommendations'; },
    value => { value.pending_count=1; },
    value => { value.hit_rate=1.1; },
    value => { value.calibration[0].count=1; },
    value => { value.baseline_zero_brier=0.9; },
    value => { value.hit_rate_interval=[0.6,0.9]; },
    value => { value.clv_game_cluster_count=3; },
    value => { delete value.roi_game_cluster_count; },
    value => { value.profit_scope='realized profit'; value.roi=Number.NaN; },
  ]) {
    const value=report(); mutate(value);
    assert.throws(()=>publicMetrics(value,'all'));
  }
});

test('public metrics rejects unsafe model identifiers', () => {
  const value=report();value.model_version='<script>alert(1)</script>';
  assert.throws(()=>publicMetrics(value,'all'));
});
