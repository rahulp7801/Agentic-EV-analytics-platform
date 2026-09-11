import test from 'node:test';
import assert from 'node:assert/strict';
import {scanStatus} from '../lib/scanStatus.ts';

const now=Date.parse('2026-09-11T12:00:00Z');
const completed={status:'complete',finished_at:'2026-09-11T11:59:00Z',eligible_events:2,completed_events:2,
  budget_skipped_events:0,failures:[],coverage:{game:{quotes:12}}};
test('scan health distinguishes missing, partial, empty and stale evidence',()=>{
  assert.equal(scanStatus(null,now).state,'not_run');
  assert.equal(scanStatus(completed,now).state,'complete');
  assert.equal(scanStatus({...completed,budget_skipped_events:1},now).state,'partial');
  assert.equal(scanStatus({...completed,coverage:{}},now).state,'no_quotes');
  assert.equal(scanStatus({...completed,eligible_events:0,completed_events:0,coverage:{}},now).state,'no_games');
  assert.equal(scanStatus({...completed,failures:[{}]},now).state,'degraded');
  assert.equal(scanStatus(completed,now+46*60000).state,'stale');
  assert.equal(scanStatus({...completed,finished_at:'invalid'},now).state,'unknown');
});
test('interrupted scans do not stay green or running indefinitely',()=>{
  const running={...completed,status:'running',finished_at:null,started_at:completed.finished_at};
  assert.equal(scanStatus(running,now).state,'running');
  assert.equal(scanStatus(running,now+21*60000).state,'interrupted');
});
