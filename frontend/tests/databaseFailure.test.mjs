import assert from 'node:assert/strict';
import test from 'node:test';
import {databaseFailure,reportDatabaseFailure,reportGameLogValidationFailure} from '../lib/databaseFailure.ts';
import {queryWithClient} from '../lib/queryWithClient.ts';

const secret='postgres://private-user:private-password@private-host/internal-table';

test('database diagnostics classify known failures without emitting raw error properties',()=>{
  for(const [code,category] of [['53300','connection_limit'],['57014','query_cancelled'],['28P01','authentication'],
    ['42501','permission'],['42P01','schema'],['ECONNRESET','connection_reset'],['ETIMEDOUT','network_timeout'],
    ['ENOTFOUND','dns'],['SELF_SIGNED_CERT_IN_CHAIN','tls'],['57P01','database_unavailable']]) {
    const error=Object.assign(new Error(secret),{code,detail:secret,query:secret,parameters:[secret],stack:secret});
    const record=databaseFailure(error,'query','gamelogs',12.4,3);
    assert.deepEqual(record,{event:'dashboard_database_failure',operation:'gamelogs',phase:'query',category,elapsed_ms:12,active_queries:3});
    assert.equal(JSON.stringify(record).includes('private'),false);
  }
  for(const error of [{code:secret,message:secret},null,secret,{code:'__proto__'},new Proxy({}, {get(){throw new Error(secret);}})]) {
    assert.equal(databaseFailure(error,'query','gamelogs',0,1).category,'unknown');
  }
});

test('pg timeouts and cancellations are classified without guessing arbitrary message contents',()=>{
  assert.equal(databaseFailure(new Error('timeout expired'),'connect','gamelogs',0,1).category,'connection_timeout');
  assert.equal(databaseFailure(new Error('timeout expired'),'query','gamelogs',0,1).category,'unknown');
  assert.equal(databaseFailure(new Error('Query read timeout'),'query','gamelogs',0,1).category,'query_timeout');
  assert.equal(databaseFailure(new Error('timeout expired '+secret),'connect','gamelogs',0,1).category,'unknown');
  assert.deepEqual(databaseFailure(new Error(secret),secret,secret,NaN,Infinity),{
    event:'dashboard_database_failure',operation:'unspecified',phase:'unknown',category:'unknown',elapsed_ms:0,active_queries:0});
});

test('connect and query failures retain original errors and close clients, even if observer fails',async()=>{
  for(const phase of ['connect','query']) {
    let ended=0;const events=[];const error=Object.assign(new Error(secret),{code:'53300'});
    const client={async connect(){if(phase==='connect')throw error;},
      async query(){throw error;},async end(){ended++;}};
    await assert.rejects(queryWithClient(client,secret,[secret],'gamelogs',event=>events.push(event)),e=>e===error);
    assert.equal(events.length,1);assert.equal(events[0].phase,phase);
    assert.equal(events[0].active_queries,1);assert.equal(ended,1);
    await assert.rejects(queryWithClient(client,secret,[],'gamelogs',()=>{throw new Error('observer failed');}),e=>e===error);
    assert.equal(ended,2);
  }
});

test('capacity diagnostics distinguish local rejection and release slots after work completes',async()=>{
  let release;const blocked=new Promise(resolve=>{release=resolve;}),events=[];
  const client=()=>({async connect(){},async query(){await blocked;return {rows:[]};},async end(){}});
  const work=Array.from({length:6},()=>queryWithClient(client(),'select 1',[],'snapshot',event=>events.push(event)));
  await assert.rejects(queryWithClient(client(),'select 1',[],'gamelogs',event=>events.push(event)),/Service busy/);
  assert.equal(events.length,1);assert.equal(events[0].phase,'backpressure');
  assert.equal(events[0].category,'local_capacity');assert.equal(events[0].active_queries,6);
  release();await Promise.all(work);
  await queryWithClient(client(),'select 1',[],'gamelogs',event=>events.push(event));
  assert.equal(events.length,1);
});

test('cleanup failures are diagnostic and do not replace successful query results',async()=>{
  const events=[];
  const result=await queryWithClient({async connect(){},async query(){return {rows:[{value:1}]};},
    async end(){throw Object.assign(new Error(secret),{code:'ECONNRESET'});}},'select 1',[],'gamelogs',e=>events.push(e));
  assert.equal(result.rows[0].value,1);assert.equal(events[0].phase,'close');
  assert.equal(events[0].category,'connection_reset');
});

test('server log writer emits only diagnostic records and validation has no source payload',()=>{
  const original=console.error,logs=[];
  try {
    console.error=value=>logs.push(JSON.parse(value));
    reportDatabaseFailure(databaseFailure(new Error(secret),'query','gamelogs',2,1));
    reportGameLogValidationFailure();
    assert.equal(logs.length,2);
    assert.deepEqual(logs[1],{event:'dashboard_data_failure',operation:'gamelogs',category:'invalid_public_data'});
    assert.equal(JSON.stringify(logs).includes('private'),false);
    console.error=()=>{throw new Error('logging unavailable');};
    assert.doesNotThrow(()=>reportDatabaseFailure(logs[0]));
    assert.doesNotThrow(()=>reportGameLogValidationFailure());
  } finally {console.error=original;}
});
