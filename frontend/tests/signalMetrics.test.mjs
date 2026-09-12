import test from 'node:test';
import assert from 'node:assert/strict';
import {signalMetrics, parlayScenario} from '../lib/signalMetrics.ts';
const now = Date.parse('2026-09-10T12:00:00Z');
const quote = {true_prob: .6, american_odds: -110, push_probability: 0,
  direction: 'under', sportsbook: 'draftkings', model_version: 'empirical-jeffreys-v3',
  sample_size: 30, kelly_fraction: .04, snapped_at: new Date(now).toISOString(),
  game_start_time: new Date(now + 3600000).toISOString()};
test('uses payout for expected return, separates edge and preserves Under', () => {
  const s = signalMetrics(quote, now);
  assert.equal(s.direction, 'under'); assert.equal(s.gated, false);
  assert.ok(Math.abs(s.expected_return - .145454545) < 1e-8);
  assert.ok(Math.abs(s.ev_pct - .076190476) < 1e-8);
  assert.equal(s.confidence_interval, null); assert.equal(s.strength, 'unrated');
});
test('push refunds count toward expected return', () => {
  assert.ok(Math.abs(signalMetrics({...quote, true_prob:.5, push_probability:.1},now).expected_return - .0545454545) < 1e-8);
});
test('legacy, stale, synthetic, malformed and gated estimates cannot recommend stakes', () => {
  for (const patch of [{model_version: undefined}, {snapped_at:'2020-01-01'},
    {sportsbook:'prizepicks'}, {sample_size:NaN}, {game_start_time:undefined},
    {gated:true}, {true_prob:null}, {kelly_fraction:NaN}, {direction:undefined}]) {
    const s=signalMetrics({...quote,...patch},now);
    assert.equal(s.gated,true,JSON.stringify(patch)); assert.equal(s.kelly_fraction,0);
  }
});
test('uncertainty must come from a valid reported interval', () => {
  assert.equal(signalMetrics({...quote, confidence_interval:[.9,.2]},now).confidence_interval,null);
  assert.deepEqual(signalMetrics({...quote, confidence_interval:[.4,.8]},now).confidence_interval,[.4,.8]);
});
test('parlay scenario reports dependence bounds, not an optimized joint forecast', () => {
  const s=parlayScenario([.6,.6],3);
  assert.ok(Math.abs(s.lower-.2)<1e-8); assert.equal(s.upper,.6);
  assert.equal(s.independent,.36); assert.ok(Math.abs(s.expectedReturn-.08)<1e-8);
  assert.equal(parlayScenario([.6],3),null); assert.equal(parlayScenario([.6,NaN],3),null);
});
