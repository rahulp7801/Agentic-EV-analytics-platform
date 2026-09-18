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
  const work=Array.from({length:4},()=>queryWithClient(client(),'select 1').catch(error=>error.message));
  await assert.rejects(queryWithClient(client(),'select 1'),/Service busy/);
  assert.equal(calls.filter(call=>call==='connect').length,4);
  release();await Promise.all(work);
  assert.equal(calls.filter(call=>call==='end').length,5);
  const result=await queryWithClient({async connect(){},async query(){return {rows:[]};},async end(){}},'select 1');
  assert.deepEqual(result.rows,[]);
});
