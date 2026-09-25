import assert from 'node:assert/strict';
import test from 'node:test';
import {QueryAdmission} from '../lib/queryAdmission.ts';

const fill = gate => Promise.all(Array.from({length:6}, () => gate.acquire()));

test('FIFO slot transfer preserves the cap and does not admit new arrivals first', async () => {
  const gate = new QueryAdmission(), held = await fill(gate), order = [];
  const first = gate.acquire().then(release => {order.push(1); return release;});
  const second = gate.acquire().then(release => {order.push(2); return release;});
  held[0](); held[0](); // Duplicate cleanup cannot grant two slots.
  const third = gate.acquire().then(release => {order.push(3); return release;});
  const r1 = await first;
  assert.deepEqual(order,[1]); assert.equal(gate.activeCount,6);
  r1(); const r2 = await second;
  assert.deepEqual(order,[1,2]); assert.equal(gate.activeCount,6);
  r2(); const r3 = await third;
  r3(); held.slice(1).forEach(release=>release());
  assert.deepEqual(order,[1,2,3]); assert.equal(gate.activeCount,0);
});

test('queue overflow rejects promptly and timed-out waiters never consume a slot', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const gate = new QueryAdmission(), held = await fill(gate);
  const waiting = Array.from({length:12}, () => gate.acquire().then(
    () => assert.fail('expired waiter admitted'), error => assert.match(error.message,/Service busy/)));
  await assert.rejects(gate.acquire(),/Service busy/);
  t.mock.timers.tick(1999); assert.equal(gate.activeCount,6);
  t.mock.timers.tick(1); await Promise.all(waiting);
  held.forEach(release=>release()); assert.equal(gate.activeCount,0);
  const release = await gate.acquire(); assert.equal(gate.activeCount,1);
  release(); assert.equal(gate.activeCount,0);
});

test('admitted waiter cancels its deadline; expired waiter frees queue space', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const gate = new QueryAdmission(), held = await fill(gate);
  const admitted = gate.acquire(); held[0](); const release = await admitted;
  t.mock.timers.tick(2000); assert.equal(gate.activeCount,6);
  const expired = assert.rejects(gate.acquire(),/Service busy/);
  t.mock.timers.tick(2000); await expired;
  const fresh = gate.acquire(); release(); (await fresh)();
  held.slice(1).forEach(release=>release()); assert.equal(gate.activeCount,0);
});
