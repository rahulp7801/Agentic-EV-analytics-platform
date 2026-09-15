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
