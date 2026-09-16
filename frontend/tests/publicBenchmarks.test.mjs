import test from 'node:test';
import assert from 'node:assert/strict';
import weekOne from '../data/nfl-week1-2026.json' with {type:'json'};
import {forecastChecks, publicForecastBenchmark} from '../lib/publicBenchmarks.ts';

test('published Week 1 benchmark retains verified aggregate evidence', () => {
  const bundle=publicForecastBenchmark(weekOne);
  assert.equal(bundle.game_count,15);
  assert.equal(bundle.outcome_record_count,627);
  assert.equal(bundle.benchmarks[0].evaluated_count,24);
  assert.equal(bundle.benchmarks[1].evaluated_count,146);
  assert.deepEqual(forecastChecks(bundle.benchmarks[0]),{brier:false,log_loss:false,calibration:false});
  assert.deepEqual(forecastChecks(bundle.benchmarks[1]),{brier:true,log_loss:true,calibration:false});
});

test('benchmark boundary rejects corrupted counts, scores and hashes', () => {
  assert.throws(()=>publicForecastBenchmark({...weekOne,dataset_sha256:'unsafe'}));
  assert.throws(()=>publicForecastBenchmark({...weekOne,benchmarks:[
    {...weekOne.benchmarks[0],evaluated_count:25}]}));
  assert.throws(()=>publicForecastBenchmark({...weekOne,benchmarks:[
    {...weekOne.benchmarks[0],brier_score:2}]}));
});
