import test from 'node:test';
import assert from 'node:assert/strict';
import {scheduleSnapshot} from '../lib/scheduleStatus.ts';

test('hosted schedules require recent evidence for the current Eastern date',()=>{
  const now=Date.parse('2026-09-11T18:00:00Z');
  const data={status:'complete',captured_at:'2026-09-11T17:59:00Z',as_of_date:'2026-09-11',games:[]};
  assert.equal(scheduleSnapshot(data,now).status,200);
  assert.equal(scheduleSnapshot({...data,status:'partial'},now).body.partial,true);
  for (const value of [null,{...data,status:'unavailable'},{...data,as_of_date:'2026-09-10'},
    {...data,captured_at:'2026-09-11T15:00:00Z'},{...data,captured_at:'2026-09-11T19:00:00Z'}]) {
    assert.equal(scheduleSnapshot(value,now).status,503);
  }
});
