import test from 'node:test';
import assert from 'node:assert/strict';
import { expectedProfit, signalMetrics } from '../lib/signalMetrics.ts';
import { POST, GET } from '../app/api/scan/route.ts';

test('public requests cannot start scans, including forged loopback Host headers', async () => {
  const response = await POST(new Request('http://localhost/api/scan', {method:'POST', headers:{host:'localhost'}}));
  assert.equal(response.status, 403);
  assert.equal((await (await GET()).json()).managed, true);
});

test('dollar profit uses expected return at actual payout, not probability edge', () => {
  const s = signalMetrics({true_prob:.6,american_odds:100,direction:'over',model_version:'empirical-jeffreys-v4',sportsbook:'book'});
  assert.ok(Math.abs(expectedProfit(s.expected_return, 100)-20)<1e-10);
  assert.equal(expectedProfit(null, 100), null);
  assert.equal(expectedProfit(.2, -100), null);
});
