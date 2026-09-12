import test from 'node:test';
import assert from 'node:assert/strict';
import {signalMetrics,publicSignals,publicSignalSnapshots,parlayScenario} from '../lib/signalMetrics.ts';
const now = Date.parse('2026-09-10T12:00:00Z');
const quote = {true_prob: .6, american_odds: -110, push_probability: 0,
  direction: 'under', sportsbook: 'draftkings', model_version: 'empirical-jeffreys-v4',
  sample_size: 30, kelly_fraction: .04, snapped_at: new Date(now).toISOString(),
  game_start_time: new Date(now + 3600000).toISOString()};
const publicQuote={...quote,id:'prediction',player:'Player',team:'',opponent:'',
  home_team:'Home',away_team:'Away',game_id:'game',sport:'nfl',prop_type:'pass_yds',line:249.5,
  mean_stat:260,confidence_interval:[.5,.7],trade_plan:[],injury_flags:{},
  market_type:'player_pass_yds',strength:'unrated'};
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
  for (const patch of [{model_version: undefined}, {model_version:'empirical-jeffreys-v3'}, {snapped_at:'2020-01-01'},
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
test('public signals require real identity and price fields and omit internal data', () => {
  const value={...publicQuote,internal_evidence:'private implementation detail'};
  const result=publicSignals([value,{...value,sportsbook:undefined},{...value,american_odds:-105.5},
    {...value,sportsbook:'PrizePicks'}],now);
  assert.equal(result.invalid_signals,3);
  assert.equal(result.signals.length,1);
  assert.equal(result.signals[0].sportsbook,'draftkings');
  assert.equal(result.signals[0].american_odds,-110);
  assert.equal(result.signals[0].sport,'nfl');
  assert.equal(result.signals[0].prop_type,'pass_yds');
  assert.equal('internal_evidence' in result.signals[0],false);
});
test('public signals never fill missing fields with plausible market data', () => {
  for (const field of ['sport','prop_type','direction','line','true_prob','sportsbook','american_odds']) {
    const changed={...publicQuote};delete changed[field];
    assert.deepEqual(publicSignals([changed],now),{signals:[],invalid_signals:1},field);
  }
  for (const changed of [{...publicQuote,true_prob:1.1},{...publicQuote,push_probability:-.1},
    {...publicQuote,true_prob:.9,push_probability:.2}]) {
    assert.deepEqual(publicSignals([changed],now),{signals:[],invalid_signals:1});
  }
});
test('public signal snapshots project bounded metadata and strip stored internals',()=>{
  const snapshot={generated_at:new Date(now).toISOString(),signals:[publicQuote],coverage:{internal:true},
    games:[{game_id:'game',home_team:'Home',away_team:'Away',date:'20260910',sport:'nfl',secret:'hidden'}]};
  const result=publicSignalSnapshots([snapshot],now);
  assert.equal(result.generated_at,snapshot.generated_at);assert.equal(result.signals.length,1);
  assert.deepEqual(result.games,[{game_id:'game',home_team:'Home',away_team:'Away',date:'20260910',sport:'nfl'}]);
  assert.equal('coverage' in result,false);assert.equal('secret' in result.games[0],false);
});
test('public signal snapshots reject malformed envelopes and bound attacker-controlled text',()=>{
  const snapshot={generated_at:new Date(now).toISOString(),signals:[publicQuote],games:[]};
  for(const changed of [{...snapshot,generated_at:'today'},
    {...snapshot,games:[{game_id:'game',home_team:'Home',away_team:'Away',date:'20260231',sport:'nfl'}]},
    {...snapshot,games:[{game_id:'game',home_team:'Home',away_team:'Away',date:'20260910',sport:'mlb'}]}]) {
    assert.throws(()=>publicSignalSnapshots([changed],now));
  }
  assert.deepEqual(publicSignals([{...publicQuote,player:'x'.repeat(101)}],now),
    {signals:[],invalid_signals:1});
  assert.throws(()=>publicSignals(Array(5001).fill(publicQuote),now));
});
test('parlay scenario reports dependence bounds, not an optimized joint forecast', () => {
  const s=parlayScenario([.6,.6],3);
  assert.ok(Math.abs(s.lower-.2)<1e-8); assert.equal(s.upper,.6);
  assert.equal(s.independent,.36); assert.ok(Math.abs(s.expectedReturn-.08)<1e-8);
  assert.equal(parlayScenario([.6],3),null); assert.equal(parlayScenario([.6,NaN],3),null);
});
