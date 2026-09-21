import assert from 'node:assert/strict';
import test from 'node:test';
import {assistantReasons,assistedSlip,dependenceEnvelope,expectedSlipReturn,MAX_SLIP_LEGS,slipWarnings} from '../lib/slipBuilder.ts';

const now=Date.parse('2026-09-20T12:00:00Z');
function pick(id,overrides={}) {
  return {id,game_id:`game-${id}`,player:`Player ${id}`,team:`T${id}`,sport:'nfl',prop_type:'pass_yds',
    line:225.5,direction:'over',true_prob:.65,implied_prob:.5,ev_pct:.15,expected_return:.2,
    push_probability:0,confidence_interval:[.56,.73],model_version:'empirical-jeffreys-v4',
    game_start_time:'2026-09-22T00:00:00Z',kelly_fraction:.02,american_odds:-110,
    sportsbook:'book',trade_plan:[],injury_flags:{},market_type:'player_prop',
    snapped_at:'2026-09-20T11:59:00Z',strength:'unrated',gated:false,sample_size:40,
    prediction_id:id,captured_at:'2026-09-20T11:59:00Z',lock_at:'2026-09-21T23:00:00Z',
    board_state:'recorded',selection_policy_version:'pregame-t60-v1',...overrides};
}

test('assistant uses only approved future records and one player exposure per game',()=>{
  const records=[pick('best',{true_prob:.7,confidence_interval:[.62,.77]}),
    pick('duplicate',{game_id:'game-best',player:'Player best',confidence_interval:[.6,.7]}),
    pick('gated',{gated:true}),pick('started',{game_start_time:'2026-09-20T11:00:00Z'}),
    ...Array.from({length:6},(_,index)=>pick(`extra-${index}`))];
  const result=assistedSlip(records,'balanced',now,99);
  assert.equal(result[0].id,'best');
  assert.ok(result.length<=MAX_SLIP_LEGS);
  assert.equal(result.some(row=>row.id==='duplicate' || row.id==='gated' || row.id==='started'),false);
});

test('assistant modes are deterministic and prefer distinct games',()=>{
  const sameGame=pick('same',{game_id:'game-a',true_prob:.8,confidence_interval:[.57,.9]});
  const records=[pick('a',{game_id:'game-a',true_prob:.66,confidence_interval:[.6,.72]}),sameGame,
    pick('b',{game_id:'game-b',true_prob:.61,confidence_interval:[.59,.68]})];
  assert.deepEqual(assistedSlip(records,'conservative',now).map(row=>row.id),['same','a']);
  const balanced=assistedSlip(records,'balanced',now);
  assert.deepEqual(balanced.slice(0,2).map(row=>row.game_id),['game-a','game-b']);
  assert.deepEqual(assistedSlip(records,'diversified',now).map(row=>row.id),balanced.map(row=>row.id));
  const broad=Array.from({length:5},(_,index)=>pick(`broad-${index}`));
  assert.equal(assistedSlip(broad,'balanced',now).length,3);
  assert.equal(assistedSlip(broad,'diversified',now).length,4);
});

test('slip analysis exposes dependence and recorded-price limitations',()=>{
  const records=[pick('a',{game_id:'shared',team:'LAR',true_prob:.6}),pick('b',{game_id:'shared',team:'LAR',true_prob:.6})];
  const envelope=dependenceEnvelope(records);
  assert.deepEqual(envelope,{independent:.36,lower:.19999999999999996,upper:.6});
  const returns=expectedSlipReturn(envelope,3);
  assert.ok(Math.abs(returns.independent-.08)<1e-12);
  assert.ok(Math.abs(returns.lower+.4)<1e-12);
  assert.ok(Math.abs(returns.upper-.8)<1e-12);
  assert.equal(expectedSlipReturn(envelope,1),null);
  assert.equal(expectedSlipReturn(envelope,100001),null);
  const warnings=slipWarnings(records).join(' ');
  assert.match(warnings,/same-game/);assert.match(warnings,/share a team/);assert.match(warnings,/repriced/);
  assert.match(assistantReasons(records,'balanced').join(' '),/screening evidence only/);
  assert.match(assistantReasons(records,'balanced',true)[0],/edited slip/i);
});

test('an empty or single-leg slip has no invented joint probability',()=>{
  assert.equal(dependenceEnvelope([]),null);
  assert.equal(dependenceEnvelope([pick('a')]),null);
  assert.match(assistantReasons([],'balanced')[0],/will not manufacture/);
});
