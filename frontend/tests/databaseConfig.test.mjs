import test from 'node:test';
import assert from 'node:assert/strict';
import { databaseConfig } from '../lib/databaseConfig.ts';

test('custom CA preserves credentials and enforces certificate and hostname verification', () => {
  const value='postgresql+psycopg://reader.project:p%40ss@pooler.example:5432/postgres?sslmode=verify-full';
  const config=databaseConfig(value,'CA contents');
  const parsed=new URL(config.connectionString);
  assert.equal(parsed.hostname,'pooler.example');
  assert.equal(parsed.password,'p%40ss');
  assert.equal(parsed.username,'reader.project');
  assert.equal(parsed.searchParams.has('sslmode'),false);
  assert.deepEqual(config.ssl,{ca:'CA contents',rejectUnauthorized:true});
  assert.throws(()=>databaseConfig(value.replace('verify-full','require'),'CA'),/verify-full/);
  assert.throws(()=>databaseConfig(undefined),/unavailable/);
  assert.equal(new URL(databaseConfig(value).connectionString).searchParams.get('sslmode'),'verify-full');
});

test('hosted connections cannot silently use plaintext or skip certificate verification',()=>{
  const value='postgresql://reader:synthetic@pooler.example/postgres';
  for(const suffix of ['', '?sslmode=disable','?sslmode=require','?sslmode=no-verify']) {
    assert.throws(()=>databaseConfig(value+suffix,undefined,true),/verification/);
  }
  assert.ok(databaseConfig(value+'?sslmode=verify-full','Public CA',true).ssl.rejectUnauthorized);
  assert.ok(databaseConfig('postgresql://localhost/sportsbet').connectionString);
});
