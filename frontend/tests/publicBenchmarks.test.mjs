import test from 'node:test';
import assert from 'node:assert/strict';
import priorWeekOne from '../data/nfl-week1-2025-receptions.json' with {type:'json'};
import priorWeekTwo from '../data/nfl-week2-2025-receptions.json' with {type:'json'};
import weekOne from '../data/nfl-week1-2026.json' with {type:'json'};
import {forecastChecks, forecastCohort, forecastEvidenceGate, forecastResult, highestConvictionForecast,
  publicForecastBenchmark} from '../lib/publicBenchmarks.ts';

test('published Week 1 benchmark retains verified aggregate evidence', () => {
  const bundle=publicForecastBenchmark(weekOne);
  assert.equal(bundle.game_count,15);
  assert.equal(bundle.outcome_record_count,627);
  assert.equal(bundle.benchmarks[0].evaluated_count,24);
  assert.equal(bundle.benchmarks[1].evaluated_count,146);
  assert.equal(bundle.records.length,170);
  assert.equal(bundle.records.filter(record=>forecastResult(record).correct).length,123);
  assert.deepEqual(forecastResult(bundle.records[0]),{side:'over',correct:false});
  assert.deepEqual(forecastChecks(bundle.benchmarks[0]),{brier:false,log_loss:false,calibration:false});
  assert.deepEqual(forecastChecks(bundle.benchmarks[1]),{brier:true,log_loss:true,calibration:false});
});

test('fixed conviction filter reports every win and loss without changing the denominator', () => {
  const bundle=publicForecastBenchmark(weekOne);
  const all=forecastCohort(bundle.records);
  const highest=forecastCohort(bundle.records.filter(highestConvictionForecast));
  assert.deepEqual({sample:all.sample,correct:all.correct,games:all.game_count},
    {sample:170,correct:123,games:15});
  assert.equal(all.hit_rate,123/170);
  assert.deepEqual({sample:highest.sample,correct:highest.correct,games:highest.game_count},
    {sample:142,correct:112,games:15});
  assert.equal(highest.hit_rate,112/142);
  assert.ok(highest.game_cluster_interval[0] > .72);
  assert.ok(highest.game_cluster_interval[1] < .85);
  assert.equal(forecastEvidenceGate(all),false);
  assert.equal(forecastEvidenceGate(highest),true);
});

test('the same conviction rule replicates across separate 2025 and 2026 reception cohorts', () => {
  const prior=[priorWeekOne,priorWeekTwo].map(publicForecastBenchmark);
  const current=publicForecastBenchmark(weekOne);
  const historical=forecastCohort(prior.flatMap(bundle=>bundle.records)
    .filter(highestConvictionForecast));
  const holdout=forecastCohort(current.records
    .filter(record=>record.prop_type==='receptions')
    .filter(highestConvictionForecast));
  assert.deepEqual({sample:historical.sample,correct:historical.correct,games:historical.game_count},
    {sample:213,correct:180,games:26});
  assert.deepEqual({sample:holdout.sample,correct:holdout.correct,games:holdout.game_count},
    {sample:122,correct:100,games:15});
  assert.ok(historical.game_cluster_interval[0]>.79);
  assert.ok(holdout.game_cluster_interval[0]>.72);
  assert.equal(forecastEvidenceGate(historical),true);
  assert.equal(forecastEvidenceGate(holdout),true);
});

test('benchmark evidence binds each result to its threshold and ESPN source', () => {
  for (const mutate of [
    value => { value.records[0].outcome=true; },
    value => { value.records[0].source_url='https://example.com/proof'; },
    value => { value.records[0].source_sha256='unsafe'; },
    value => { value.records[0].research_threshold=199.5; },
    value => { value.records.push(value.records[0]); },
  ]) {
    const value=structuredClone(weekOne);mutate(value);
    assert.throws(()=>publicForecastBenchmark(value));
  }
});

test('benchmark boundary rejects corrupted counts, scores and hashes', () => {
  assert.throws(()=>publicForecastBenchmark({...weekOne,dataset_sha256:'unsafe'}));
  assert.throws(()=>publicForecastBenchmark({...weekOne,benchmarks:[
    {...weekOne.benchmarks[0],evaluated_count:25}]}));
  assert.throws(()=>publicForecastBenchmark({...weekOne,benchmarks:[
    {...weekOne.benchmarks[0],brier_score:2}]}));
});
