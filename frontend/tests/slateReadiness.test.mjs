import test from 'node:test';
import assert from 'node:assert/strict';
import {slateReadiness,settlementProgress} from '../lib/slateReadiness.ts';
import {WEEK_ONE_DEMO,demoResult} from '../lib/weekOneDemo.ts';
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
