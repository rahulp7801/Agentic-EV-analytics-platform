import test from 'node:test';
import assert from 'node:assert/strict';
import {scanStatus} from '../lib/scanStatus.ts';

const now=Date.parse('2026-09-11T12:00:00Z');
const completed={status:'complete',finished_at:'2026-09-11T11:59:00Z',eligible_events:2,completed_events:2,
  budget_skipped_events:0,failures:[],coverage:{game:{quotes:12,selections:10,model_requests:10,model_estimates:10}}};
test('scan health distinguishes missing, partial, empty and stale evidence',()=>{
  assert.equal(scanStatus(null,now).state,'not_run');
  assert.equal(scanStatus(completed,now).state,'complete');
  assert.equal(scanStatus({...completed,budget_skipped_events:1},now).state,'partial');
  assert.equal(scanStatus({...completed,coverage:{}},now).state,'unknown');
  assert.equal(scanStatus({...completed,coverage:{game:{quotes:0,selections:0,model_requests:0,model_estimates:0}}},now).state,'no_quotes');
  assert.equal(scanStatus({...completed,eligible_events:0,completed_events:0,coverage:{}},now).state,'no_games');
  assert.equal(scanStatus({...completed,failures:[{}]},now).state,'degraded');
  assert.equal(scanStatus({...completed,status:'degraded'},now).state,'degraded');
  assert.equal(scanStatus({...completed,status:'blocked'},now).state,'blocked');
  assert.equal(scanStatus({...completed,status:'failed'},now).state,'failed');
  assert.equal(scanStatus(completed,now+46*60000).state,'stale');
  assert.equal(scanStatus({...completed,finished_at:'invalid'},now).state,'unknown');
});
test('scan health exposes quote and model coverage separately',()=>{
  const status=scanStatus({...completed,status:'degraded',coverage:{game:{quotes:12,selections:10,model_requests:8,model_estimates:7}}},now);
  assert.equal(status.quotes,12);
  assert.equal(status.selections,10);
  assert.equal(status.model_requests,8);
  assert.equal(status.model_estimates,7);
  assert.equal(status.unresolved_selections,2);
  assert.equal(status.missing_estimates,1);
  assert.equal(status.label,'Player history coverage incomplete');
});
test('budget-skipped scans explain the provider limit without implying model failure',()=>{
  const limited={...completed,status:'degraded',completed_events:0,budget_skipped_events:2,coverage:{}};
  assert.equal(scanStatus(limited,now).label,'Scan paused: API budget');
  assert.equal(scanStatus(limited,now).state,'partial');
  assert.equal(scanStatus({...limited,completed_events:1},now).label,'Coverage limited: API budget');
  assert.equal(scanStatus({...limited,failures:[{}]},now).label,'Scan had failures');
  assert.equal(scanStatus({...completed,eligible_events:0,completed_events:0,coverage:{}},now).label,'No upcoming games in scan window');
});
test('scan health rejects impossible or falsely complete model funnels',()=>{
  assert.equal(scanStatus({...completed,coverage:{game:{selections:2,model_requests:3,model_estimates:3}}},now).state,'unknown');
  assert.equal(scanStatus({...completed,coverage:{game:{selections:3,model_requests:3,model_estimates:2}}},now).state,'unknown');
});
test('interrupted scans do not stay green or running indefinitely',()=>{
  const running={...completed,status:'running',finished_at:null,started_at:completed.finished_at};
  assert.equal(scanStatus(running,now).state,'running');
  assert.equal(scanStatus(running,now+21*60000).state,'interrupted');
});

test('cadence waits are distinct from fresh quotes and provider failures',()=>{
  const waiting={...completed,status:'scheduled',completed_events:0,coverage:{},cadence_deferred_events:2};
  assert.equal(scanStatus(waiting,now).state,'scheduled');
  assert.equal(scanStatus(waiting,now).label,'Waiting for next quote check');
  assert.equal(scanStatus({...waiting,budget_skipped_events:1},now).state,'partial');
  assert.equal(scanStatus({...waiting,failures:[{}]},now).state,'degraded');
  assert.equal(scanStatus(waiting,now+46*60000).state,'stale');
});
test('next check exposes only bounded future timezone-aware scheduled timestamps',()=>{
  const waiting={...completed,status:'scheduled',completed_events:0,coverage:{},cadence_deferred_events:2,next_refresh_at:'2026-09-11T13:00:00Z'};
  assert.equal(scanStatus(waiting,now).next_refresh_at,waiting.next_refresh_at);
  for(const value of ['invalid','2026-09-11T13:00:00','2026-09-10T13:00:00Z','2026-09-14T13:00:00Z']) assert.equal(scanStatus({...waiting,next_refresh_at:value},now).next_refresh_at,null);
  assert.equal(scanStatus({...waiting,status:'degraded'},now).next_refresh_at,null);
  assert.equal(scanStatus(null,now).next_refresh_at,null);
});


test('missing coverage remains unknown instead of becoming zero model output',()=>{
  for(const coverage of [undefined,null,[],{game:null},{game:{quotes:12}}]) {
    const status=scanStatus({...completed,coverage},now);
    assert.equal(status.model_estimates,null);
    assert.equal(status.selections,null);
    assert.equal(status.state,'unknown');
  }
});

test('a due quote check stays visible after the scan becomes stale',()=>{
  const waiting={...completed,status:'scheduled',completed_events:0,coverage:{},
    cadence_deferred_events:2,next_refresh_at:'2026-09-11T12:05:00Z'};
  const due=Date.parse(waiting.next_refresh_at);
  assert.equal(scanStatus(waiting,due-1).state,'scheduled');
  for(const at of [due,due+3600000]) {
    const status=scanStatus(waiting,at);
    assert.equal(status.state,'overdue');
    assert.equal(status.overdue_at,waiting.next_refresh_at);
    assert.equal(status.next_refresh_at,null);
  }
});

test('timezone-free timestamps cannot report healthy collection',()=>{
  assert.equal(scanStatus({...completed,finished_at:'2026-09-11T11:59:00'},now).state,'unknown');
  assert.equal(scanStatus({...completed,finished_at:'2026-09-11T11:59:00'},now).updated_at,null);
});

test('contradictory event funnels cannot cancel each other out',()=>{
  const status=scanStatus({...completed,coverage:{
    one:{quotes:12,selections:10,model_requests:12,model_estimates:12},
    two:{quotes:12,selections:10,model_requests:8,model_estimates:8},
  }},now);
  assert.equal(status.state,'unknown');
  assert.equal(status.unresolved_selections,null);
});

test('nonobject coverage cannot crash the league status endpoint',()=>{
  for(const coverage of [42,'secret',{game:null},{game:[]},{game:42}]) {
    assert.doesNotThrow(()=>scanStatus({...completed,coverage},now));
    assert.equal(scanStatus({...completed,coverage},now).state,'unknown');
  }
});


test('budget reasons distinguish protected credits from hard allowance limits',()=>{
  const limited={...completed,status:'degraded',completed_events:0,budget_skipped_events:2,coverage:{}};
  for(const [reason,label] of Object.entries({
    pregame_credit_reserve:'Credits reserved for pregame checks',
    daily_credit_limit:'Waiting for daily API allowance',
    rolling_credit_limit:'Waiting for rolling API allowance',
  })) assert.equal(scanStatus({...limited,budget_reasons:{[reason]:2}},now).label,label);
  for(const reasons of [null,[],{private_error:2},{pregame_credit_reserve:1},{pregame_credit_reserve:'2'},
    {pregame_credit_reserve:1,daily_credit_limit:1}]) {
    assert.equal(scanStatus({...limited,budget_reasons:reasons},now).label,'Scan paused: API budget');
  }
});
