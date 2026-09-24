import test from 'node:test';
import benchmark from '../data/nfl-week1-2026.json' with {type:'json'};
import assert from 'node:assert/strict';
import {slateReadiness,settlementProgress} from '../lib/slateReadiness.ts';
import {WEEK_ONE_DEMO,demoResult,demoHistory,DEFAULT_DEMO_INDEX} from '../lib/weekOneDemo.ts';
import {liveSchedule} from '../lib/liveSchedule.ts';
import {scheduleSnapshot} from '../lib/scheduleStatus.ts';
const now=Date.parse('2026-09-18T16:00:00Z');
const game={home_name:'Washington Commanders',away_name:'Dallas Cowboys',home_abbr:'WSH',away_abbr:'DAL',
  game_time:'2026-09-20T17:00:00Z',date:'20260920',provider_event_id:'source'};
const scan={finished_at:new Date(now).toISOString(),status:'complete',events:[{home_team:game.home_name,away_team:game.away_name,
  game_start_time:game.game_time,game_id:'book-event',state:'evaluated'}],coverage:{'book-event':{quotes:12,selections:10,
  model_requests:8,model_estimates:7,model_status:'partial',counts:{accepted:1,unknown_or_ambiguous_player:2,teammate_availability_unmodeled:6}}}};
test('seven-day fixtures are visible before the scan horizon and never claim evaluation from missing evidence',()=>{
  assert.equal(slateReadiness([game],null,now)[0].state,'Outside the 48-hour scan window');
  assert.equal(slateReadiness([game],null,now+2*3600000)[0].state,'Waiting for scan');
  assert.deepEqual(slateReadiness([{...game,completed:true}],scan,now),[]);
  assert.equal(slateReadiness([game],{...scan,events:[{...scan.events[0],game_start_time:'2026-09-20T18:00:00Z'}]},now)[0].state,'Outside the 48-hour scan window');
});
test('in-progress games stay visible but permanently lock every pick state',()=>{
  const live={...game,game_time:new Date(now-1).toISOString(),date:'20260918'};
  const result=slateReadiness([live],{...scan,events:[{...scan.events[0],game_start_time:live.game_time}]},now)[0];
  assert.equal(result.state,'Live · picks locked');assert.equal(result.locked,true);
  assert.equal(result.model_estimates,null);assert.equal(result.accepted_at_capture,null);
  assert.deepEqual(result.reasons,[]);
});
test('exact game joins retain model gaps, risk reasons and acceptance at capture separately',()=>{
  const result=slateReadiness([game],scan,now)[0];
  assert.equal(result.state,'Player/model coverage incomplete');assert.equal(result.model_estimates,7);
  assert.equal(result.unresolved_selections,2);assert.equal(result.accepted_at_capture,1);
  assert.equal(result.reasons.length,2);assert.equal('game_id' in result,false);
  assert.equal(slateReadiness([game],{...scan,finished_at:new Date(now-46*60000).toISOString()},now)[0].state,'Scan evidence is stale');
  assert.equal(slateReadiness([game],{...scan,events:[scan.events[0],scan.events[0]]},now)[0].model_estimates,null);
  for(const state of ['api_budget','scheduled','failed']) assert.notEqual(slateReadiness([game],{...scan,events:[{...scan.events[0],state}]},now)[0].state,'Evaluated');
});
test('settlement progress cannot fabricate verified totals from impossible counts or monitor placeholders',()=>{
  const report={finished_at:new Date(now).toISOString(),settlements:{nfl:{status:'complete',candidates:10,settled:2,pending:8,
    outside_schedule:3,reasons:{stat_not_found_or_ambiguous:8,private:'secret'}}}};
  const value=settlementProgress([report],'nfl',now);
  assert.equal(value.settled,2);assert.equal(value.reasons.length,1);assert.equal(JSON.stringify(value).includes('secret'),false);
  assert.equal(settlementProgress([{...report,settlements:{nfl:{status:'not_requested'}}}],'nfl',now),null);
  assert.equal(settlementProgress([report,{finished_at:new Date(now+1000).toISOString(),
    settlements:{nfl:{status:'not_requested'}}}],'nfl',now).settled,2);
  assert.equal(settlementProgress([{...report,settlements:{nfl:{...report.settlements.nfl,settled:20}}}],'nfl',now),null);
});
test('static retrospective demo retains both correct and missed baselines and never produces a pick or profit',()=>{
  const results=WEEK_ONE_DEMO.map(demoResult);assert.equal(results.filter(r=>r.correct).length,2);
  assert.equal(WEEK_ONE_DEMO[DEFAULT_DEMO_INDEX].player,'Brock Purdy');
  assert.equal(demoResult(WEEK_ONE_DEMO[DEFAULT_DEMO_INDEX]).correct,true);
  assert.equal(results.filter(r=>!r.correct).length,1);
  for(const result of results) {assert.equal(result.historical_price,null);assert.equal(result.profit,null);assert.equal(result.execution_ready,false);assert.equal(result.recommendation,'Research only');}
});
test('future scoreboard dates and week-wide NFL responses produce seven-day coverage without duplicate fixtures',async t=>{
  const requested=[];
  t.mock.method(globalThis,'fetch',async url=>{
    requested.push(url);
    return Response.json({events:[{id:'sunday',date:game.game_time,competitions:[{status:{type:{completed:false}},competitors:[
      {homeAway:'home',team:{abbreviation:'WSH',displayName:game.home_name}},
      {homeAway:'away',team:{abbreviation:'DAL',displayName:game.away_name}}]}]}]});
  });
  const result=await liveSchedule('nfl',now,6);assert.equal(result.status,200);
  assert.equal(result.body.games.length,1);assert.equal(result.body.games[0].date,'20260920');assert.equal(requested.length,8);
});

test('worker-captured future fixtures preserve source identity and cannot silently use stale or short windows',()=>{
  const captured={sport:'nfl',status:'complete',partial:false,as_of_date:'2026-09-18',
    captured_at:new Date(now).toISOString(),games:[{...game,date:'20260920',label:'2026-09-20',completed:false}]};
  const result=scheduleSnapshot(captured,'nfl',now,6);
  assert.equal(result.status,200);assert.equal(result.body.games[0].provider_event_id,'source');
  assert.equal(scheduleSnapshot(captured,'nfl',now).status,503);
  assert.equal(scheduleSnapshot({...captured,captured_at:new Date(now-5*3600000).toISOString()},'nfl',now,6).status,503);
});

test('demo explanations reconstruct each retained forecast from actual pregame history',()=>{
  const expected={'Brock Purdy':[17,24,3],'Matthew Stafford':[24,33,5],'Aaron Rodgers':[21,33,4]};
  for(const record of WEEK_ONE_DEMO) {
    const history=demoHistory(record),[hits,count,recent]=expected[record.player];
    const retained=benchmark.records.find(row=>row.player_name===record.player && row.prop_type==='pass_yds');
    assert.equal(retained.sample_size,record.sample);assert.equal(retained.model_probability,record.probability);
    assert.equal(retained.actual_value,record.actual);assert.equal(retained.research_threshold,record.threshold);
    assert.equal(history.above,hits);assert.equal(history.games.length,count);
    assert.equal(history.games.length,record.sample);assert.equal(history.recentAbove,recent);
    assert.ok(Math.abs(history.probability-record.probability)<.000001);
    assert.equal(new Set(history.games.map(game=>game.date)).size,count);
    for(const game of history.games) {assert.ok(game.date<record.date);assert.ok(game.date>='2024-01-01');assert.ok(Number.isFinite(game.yards));}
    assert.equal(history.games.some(game=>game.date===record.date),false);
  }
  const purdy=demoHistory(WEEK_ONE_DEMO[DEFAULT_DEMO_INDEX]);
  assert.deepEqual(purdy.recent.map(game=>game.yards),[127,303,295,295,168]);
  assert.ok(purdy.recentAbove/5<purdy.above/purdy.games.length);
});


test('game budget status distinguishes reserve from exhausted allowance and never trusts arbitrary messages',()=>{
  for(const [reason,label] of Object.entries({pregame_credit_reserve:'Credits reserved for pregame checks',daily_credit_limit:'Waiting for daily API allowance',rolling_credit_limit:'Waiting for rolling API allowance'})) {
    const report={...scan,events:[{...scan.events[0],state:'api_budget',budget_reason:reason}]};
    assert.equal(slateReadiness([game],report,now)[0].state,label);
    assert.equal(slateReadiness([game],report,now+46*60000)[0].state,'Scan evidence is stale');
    assert.equal(slateReadiness([game],report,Date.parse(game.game_time))[0].state,'Live · picks locked');
  }
  for(const reason of ['private provider message','constructor','__proto__',null,{}]) {
    const report={...scan,events:[{...scan.events[0],state:'api_budget',budget_reason:reason}]};
    assert.equal(slateReadiness([game],report,now)[0].state,'API budget limited');
  }
});

test('game-specific due checks become overdue without claiming a successful refresh',()=>{
  const due=new Date(now+15*60000).toISOString();
  const report={...scan,events:[{...scan.events[0],state:'scheduled',next_refresh_at:due}]};
  const before=slateReadiness([game],report,now)[0];
  assert.equal(before.next_refresh_at,due);assert.equal(before.overdue_at,null);
  assert.equal(before.checked_at,scan.finished_at);
  for(const age of [15,20,46]) {
    const overdue=slateReadiness([game],report,now+age*60000)[0];
    assert.equal(overdue.state,'Quote check overdue');assert.equal(overdue.overdue_at,due);assert.equal(overdue.next_refresh_at,null);
  }
  const live=slateReadiness([game],report,Date.parse(game.game_time))[0];
  assert.equal(live.state,'Live · picks locked');assert.equal(live.overdue_at,null);assert.equal(live.next_refresh_at,null);
});

test('check timestamps require an exact game match and bounded scheduled evidence',()=>{
  const due=new Date(now+15*60000).toISOString();
  for(const events of [[],[scan.events[0],scan.events[0]],[{...scan.events[0],home_team:'Another team'}]]) {
    assert.equal(slateReadiness([game],{...scan,events},now)[0].checked_at,null);
  }
  for(const invalid of ['invalid','2026-09-18T16:15:00',new Date(now-21*60000).toISOString(),game.game_time,new Date(now+49*3600000).toISOString()]) {
    const report={...scan,events:[{...scan.events[0],state:'scheduled',next_refresh_at:invalid}]};
    const value=slateReadiness([game],report,now)[0];assert.equal(value.next_refresh_at,null);assert.equal(value.overdue_at,null);
  }
  for(const state of ['api_budget','evaluated','failed']) {
    const value=slateReadiness([game],{...scan,events:[{...scan.events[0],state,next_refresh_at:due}]},now)[0];
    assert.equal(value.next_refresh_at,null);assert.equal(value.overdue_at,null);
  }
  const future={...scan,finished_at:new Date(now+120000).toISOString(),events:[{...scan.events[0],state:'scheduled',next_refresh_at:due}]};
  assert.equal(slateReadiness([game],future,now)[0].checked_at,null);
});

test('reserve windows require fresh exact-game evidence and remain distinct from quote checks',()=>{
  const current=Date.parse('2026-09-20T14:00:00Z');
  const release='2026-09-20T15:00:00Z';
  const event={...scan.events[0],state:'api_budget',budget_reason:'pregame_credit_reserve',next_reserve_release_at:release};
  const recorded={...scan,status:'degraded',finished_at:new Date(current).toISOString(),events:[event]};
  const result=slateReadiness([game],recorded,current)[0];
  assert.equal(result.next_reserve_release_at,release);
  assert.equal(result.state,'Credits reserved for pregame checks');
  assert.equal(result.next_refresh_at,null);assert.equal(result.overdue_at,null);
  for(const patch of [{state:'evaluated'},{budget_reason:'daily_credit_limit'},{budget_reason:'rolling_credit_limit'},
    {next_reserve_release_at:undefined},{next_reserve_release_at:'invalid'},
    {next_reserve_release_at:'2026-09-20T15:00:00'},
    {next_reserve_release_at:'2026-09-20T14:00:00Z'},
    {next_reserve_release_at:game.game_time},{game_start_time:'2026-09-20T18:00:00Z'}]) {
    assert.equal(slateReadiness([game],{...recorded,events:[{...event,...patch}]},current)[0].next_reserve_release_at,null);
  }
  assert.equal(slateReadiness([game],{...recorded,events:[event,event]},current)[0].next_reserve_release_at,null);
  assert.equal(slateReadiness([game],recorded,current+46*60000)[0].next_reserve_release_at,null);
  assert.equal(slateReadiness([game],recorded,Date.parse(game.game_time))[0].next_reserve_release_at,null);
  assert.equal(slateReadiness([game],null,current)[0].next_reserve_release_at,null);
});
