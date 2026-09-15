import assert from 'node:assert/strict';
import test from 'node:test';
import { CURRENT_MARKET_WINDOW_MS, marketFreshness } from '../lib/marketFreshness.ts';

const now = Date.parse('2026-09-15T20:00:00Z');

test('market freshness distinguishes current, stale, future, and missing captures', () => {
  assert.equal(marketFreshness('2026-09-15T19:59:00Z', now), 'current');
  assert.equal(marketFreshness(new Date(now - CURRENT_MARKET_WINDOW_MS).toISOString(), now), 'current');
  assert.equal(marketFreshness(new Date(now - CURRENT_MARKET_WINDOW_MS - 1).toISOString(), now), 'stale');
  assert.equal(marketFreshness('2026-09-15T20:00:01Z', now), 'stale');
  assert.equal(marketFreshness('invalid', now), 'unavailable');
  assert.equal(marketFreshness(null, now), 'unavailable');
});
