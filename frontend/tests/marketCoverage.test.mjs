import test from 'node:test';
import assert from 'node:assert/strict';
import {marketCoverageText,propQuoteCoverageText,sourceFailureText} from '../lib/marketCoverage.ts';

test('provider failures expose only approved operational reasons',()=>{
  assert.equal(sourceFailureText('access_denied'),'provider access denied');
  assert.equal(sourceFailureText('rate_limited'),'provider rate limited');
  assert.equal(sourceFailureText('upstream_unavailable'),'provider temporarily unavailable');
  assert.equal(sourceFailureText('request_rejected'),'provider rejected the request');
  assert.equal(sourceFailureText('RuntimeError: secret URL'),null);
});

test('stage-specific Kalshi coverage forms two explicit partitions',()=>{
  assert.equal(marketCoverageText({discovered_games:15,attempted_games:15,observed_games:13,
    event_failed_games:2,market_failed_games:1,sample_complete_games:12,quoted_games:12,
    failed_games:3}),
  '13/15 event records observed, 2 event failures, 12 sampled games complete, 1 with partial market failures, 12 with quotes');
});

test('legacy captures keep their original non-partitioned wording',()=>{
  assert.equal(marketCoverageText({discovered_games:15,attempted_games:15,observed_games:13,
    quoted_games:12,failed_games:3}),
  '13/15 discovered games inspected, 12 with quotes, 3 with collection failures');
});

test('prop quote coverage reports an exact market and ask-side partition',()=>{
  assert.equal(propQuoteCoverageText({prop_structured_quote_markets:3081,
    prop_yes_ask_quote_markets:3081,prop_no_ask_quote_markets:2822,
    prop_two_sided_quote_markets:2822,prop_one_sided_quote_markets:259,
    prop_unquoted_markets:0}),
  '3081 structured top-of-book markets · 2822 two-sided (91.6%) · 259 one-sided (3081 YES asks, 2822 NO asks) · 0 without displayed asks');
});

test('legacy prop captures keep a bounded fallback',()=>{
  assert.equal(propQuoteCoverageText({prop_structured_quote_markets:3,
    prop_two_sided_quote_markets:2}),
  '3 structured top-of-book markets (2 two-sided)');
});
