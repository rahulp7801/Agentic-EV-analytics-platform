import assert from 'node:assert/strict';
import test from 'node:test';

import {NO_STORE_HEADERS,PUBLIC_CACHE_HEADERS,signalCacheHeaders} from '../lib/publicCache.ts';

test('public data stays out of browser caches while Vercel absorbs repeat reads',()=>{
  for(const headers of Object.values(PUBLIC_CACHE_HEADERS)) {
    assert.equal(headers['Cache-Control'],'no-store');
    assert.match(headers['Vercel-CDN-Cache-Control'],/^public, s-maxage=\d+, stale-while-revalidate=\d+$/);
  }
  assert.deepEqual(NO_STORE_HEADERS,{'Cache-Control':'no-store'});
});

test('actionable forecasts use the shortest cache lifetime',()=>{
  assert.equal(signalCacheHeaders('qualified'),PUBLIC_CACHE_HEADERS.live);
  assert.equal(signalCacheHeaders('candidates'),PUBLIC_CACHE_HEADERS.research);
  assert.equal(signalCacheHeaders('library'),PUBLIC_CACHE_HEADERS.research);
  const live=Number(PUBLIC_CACHE_HEADERS.live['Vercel-CDN-Cache-Control'].match(/s-maxage=(\d+)/)?.[1]);
  const research=Number(PUBLIC_CACHE_HEADERS.research['Vercel-CDN-Cache-Control'].match(/s-maxage=(\d+)/)?.[1]);
  assert.ok(live>0 && live<research && research<=300);
});
