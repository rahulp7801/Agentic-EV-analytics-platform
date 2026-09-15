import assert from 'node:assert/strict';
import test from 'node:test';

import {
  paidPipelinePaths,
  publicPipelinePaths,
  requiredCssMarkers,
  readinessStatuses,
  verifyProduction,
  verifyProductionWithRetry,
} from '../scripts/verify-production.mjs';

const deploymentHtml = '<html><head><link rel="stylesheet" href="/app.css"></head></html>';
const deploymentCss = requiredCssMarkers.join(' ');

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
    if (path === '/app.css') return { status: 200, text: async () => deploymentCss };
    const status = path === '/api/markets?sport=nfl' ? 503 : path === '/api/scan' ? 403 : path === '/.env' || path === '/signals_cache.json' ? 404 : 200;
    return {
      status,
      headers: { get: (name) => name === 'x-content-type-options' ? 'nosniff' : name === 'content-security-policy' ? "default-src 'self'" : null },
      text: async () => deploymentHtml,
    };
  };

  await assert.rejects(
    verifyProduction({ base: 'https://example.test', fetchImpl, paidEnabled: false, publicEnabled: true }),
    /\/api\/markets\?sport=nfl: unexpected HTTP 503/,
  );
});

test('production verification binds public endpoints to the current collection report', async () => {
  const expectedPublicReport = {
    markets: { nfl: { captured_at: '2026-09-12T23:14:02Z' } },
    schedules: { nfl: { captured_at: '2026-09-12T23:13:52Z' } },
  };
  const fetchImpl = async (url) => {
    const parsed = new URL(url);
    const path = parsed.pathname + parsed.search;
    if (path === '/app.css') return { status: 200, text: async () => deploymentCss };
    const captured_at = path === '/api/markets?sport=nfl'
      ? '2026-09-12T23:14:02Z'
      : path === '/api/games?sport=nfl'
        ? '2026-09-12T23:13:52Z'
        : undefined;
    return {
      status: path === '/api/scan' ? 403 : path === '/.env' || path === '/signals_cache.json' ? 404 : 200,
      headers: { get: (name) => name === 'x-content-type-options' ? 'nosniff' : name === 'content-security-policy' ? "default-src 'self'" : null },
      text: async () => deploymentHtml,
      json: async () => ({ captured_at }),
    };
  };

  await verifyProduction({
    base: 'https://example.test',
    fetchImpl,
    paidEnabled: false,
    publicEnabled: true,
    expectedPublicReport,
  });

  expectedPublicReport.markets.nfl.captured_at = '2026-09-12T23:15:02Z';
  await assert.rejects(
    verifyProduction({
      base: 'https://example.test',
      fetchImpl,
      paidEnabled: false,
      publicEnabled: true,
      expectedPublicReport,
    }),
    /deployed capture does not match this collection run/,
  );
});

test('production verification rejects a stale or incomplete stylesheet bundle', async () => {
  const fetchImpl = async (url) => {
    const path = new URL(url).pathname + new URL(url).search;
    if (path === '/app.css') return { status: 200, text: async () => ':root{--accent-mint:#00e5a0}' };
    return {
      status: path === '/api/scan' ? 403 : path === '/.env' || path === '/signals_cache.json' ? 404 : 200,
      headers: { get: (name) => name === 'x-content-type-options' ? 'nosniff' : name === 'content-security-policy' ? "default-src 'self'" : null },
      text: async () => deploymentHtml,
      json: async () => ({}),
    };
  };

  await assert.rejects(
    verifyProduction({ base: 'https://example.test', fetchImpl }),
    /Production stylesheet is stale or incomplete/,
  );
});

test('production verification retries a transient deployment propagation mismatch', async () => {
  let stylesheetRequests = 0;
  const fetchImpl = async (url) => {
    const path = new URL(url).pathname + new URL(url).search;
    if (path === '/app.css') {
      stylesheetRequests += 1;
      return { status: 200, text: async () => stylesheetRequests === 1 ? ':root{}' : deploymentCss };
    }
    return {
      status: path === '/api/scan' ? 403 : path === '/.env' || path === '/signals_cache.json' ? 404 : 200,
      headers: { get: (name) => name === 'x-content-type-options' ? 'nosniff' : name === 'content-security-policy' ? "default-src 'self'" : null },
      text: async () => deploymentHtml,
      json: async () => ({}),
    };
  };

  const waits = [];
  await verifyProductionWithRetry(
    { base: 'https://example.test', fetchImpl },
    { attempts: 2, delayMs: 25, wait: async delay => waits.push(delay), log: () => {} },
  );
  assert.equal(stylesheetRequests, 2);
  assert.deepEqual(waits, [25]);
});
