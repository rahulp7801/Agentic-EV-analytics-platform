import assert from 'node:assert/strict';
import test from 'node:test';
import { queryWithClient } from '../lib/queryWithClient.ts';

test('database queries always close their serverless connection', async () => {
  const calls = [];
  const client = {
    async connect() { calls.push('connect'); },
    async query(text, values) { calls.push(['query', text, values]); return { rows: [{value: 1}], rowCount: 1 }; },
    async end() { calls.push('end'); },
  };
  const result = await queryWithClient(client, 'select $1 as value', [1]);
  assert.equal(result.rows[0].value, 1);
  assert.deepEqual(calls, ['connect', ['query', 'select $1 as value', [1]], 'end']);
});

test('database queries close their connection after an error', async () => {
  let ended = false;
  const client = {
    async connect() {},
    async query() { throw new Error('query failed'); },
    async end() { ended = true; },
  };
  await assert.rejects(queryWithClient(client, 'select 1'), /query failed/);
  assert.equal(ended, true);
});

test('database backpressure caps active work and releases capacity after failures',async()=>{
  let release;const blocked=new Promise(resolve=>{release=resolve;}),calls=[];
  const client=()=>({async connect(){calls.push('connect');},async query(){await blocked;throw new Error('query failed');},async end(){calls.push('end');}});
  const work=Array.from({length:18},()=>queryWithClient(client(),'select 1').catch(error=>error.message));
  await assert.rejects(queryWithClient(client(),'select 1'),/Service busy/);
  assert.equal(calls.filter(call=>call==='connect').length,6);
  release();await Promise.all(work);
  assert.equal(calls.filter(call=>call==='end').length,19);
  const result=await queryWithClient({async connect(){},async query(){return {rows:[]};},async end(){}},'select 1');
  assert.deepEqual(result.rows,[]);
});


test('waiting queries connect only after the prior connection has finished closing',async()=>{
  let finishClose; const closing=new Promise(resolve=>{finishClose=resolve;});
  let connects=0;const blockers=[];
  const work=Array.from({length:6},(_,i)=>queryWithClient({
    async connect(){connects++;},
    async query(){return {rows:[]};},
    async end(){if(i===0)await closing;else await new Promise(resolve=>blockers.push(resolve));},
  },'select 1'));
  let queuedConnected=false;
  const queued=queryWithClient({async connect(){queuedConnected=true;connects++;},
    async query(){return {rows:[]};},async end(){}},'select 1');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(connects,6);assert.equal(queuedConnected,false);
  finishClose();await queued;assert.equal(connects,7);
  blockers.forEach(resolve=>resolve());await Promise.all(work);
});

test('admission timeout closes the unconnected client and reports bounded capacity',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  let release;const blocked=new Promise(resolve=>{release=resolve;});
  const work=Array.from({length:6},()=>queryWithClient({async connect(){},
    async query(){await blocked;return {rows:[]};},async end(){}},'select 1'));
  let ended=0,connected=0;const events=[];
  const queued=assert.rejects(queryWithClient({async connect(){connected++;},
    async query(){assert.fail('expired request queried');},async end(){ended++;}},
    'select 1',[],'gamelogs',event=>events.push(event)),/Service busy/);
  t.mock.timers.tick(2000);await queued;
  assert.equal(connected,0);assert.equal(ended,1);
  assert.equal(events.length,1);assert.equal(events[0].phase,'backpressure');
  assert.equal(events[0].category,'local_capacity');assert.equal(events[0].active_queries,6);
  release();await Promise.all(work);
});
