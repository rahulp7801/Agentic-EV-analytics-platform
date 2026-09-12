import assert from 'node:assert/strict';
import test from 'node:test';

import {
  paidPipelinePaths,
  publicPipelinePaths,
  readinessStatuses,
  verifyProduction,
} from '../scripts/verify-production.mjs';

test('public pipeline makes public endpoints mandatory without requiring paid endpoints', () => {
  const flags = { paidEnabled: false, publicEnabled: true };
  for (const path of publicPipelinePaths) assert.deepEqual(readinessStatuses(path, flags), [200]);
  for (const path of paidPipelinePaths) assert.deepEqual(readinessStatuses(path, flags), [200, 503]);
});

test('paid pipeline makes all data endpoints mandatory', () => {
  const flags = { paidEnabled: true, publicEnabled: false };
  for (const path of [...paidPipelinePaths, ...publicPipelinePaths]) {
    assert.deepEqual(readinessStatuses(path, flags), [200]);
  }
});

test('production verification rejects unavailable public data when its pipeline is enabled', async () => {
  const fetchImpl = async (url) => {
    const path = new URL(url).pathname + new URL(url).search;
    const status = path === '/api/markets?sport=nfl' ? 503 : path === '/api/scan' ? 403 : path === '/.env' || path === '/signals_cache.json' ? 404 : 200;
    return {
      status,
      headers: { get: (name) => name === 'x-content-type-options' ? 'nosniff' : name === 'content-security-policy' ? "default-src 'self'" : null },
    };
  };

  await assert.rejects(
    verifyProduction({ base: 'https://example.test', fetchImpl, paidEnabled: false, publicEnabled: true }),
    /\/api\/markets\?sport=nfl: unexpected HTTP 503/,
  );
});
