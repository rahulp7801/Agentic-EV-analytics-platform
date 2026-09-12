import test from 'node:test';
import assert from 'node:assert/strict';
import {marketCoverageText} from '../lib/marketCoverage.ts';

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
