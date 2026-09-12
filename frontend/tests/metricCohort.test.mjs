import test from 'node:test';
import assert from 'node:assert/strict';

import { metricCohort, metricLedgerArgs, metricSnapshotKey } from '../lib/metricCohort.ts';

test('metric cohort defaults to all and accepts only published cohorts', () => {
  assert.equal(metricCohort('https://example.test/api/metrics'), 'all');
  assert.equal(metricCohort('https://example.test/api/metrics?cohort=recommendations'), 'recommendations');
  assert.equal(metricCohort('https://example.test/api/metrics?cohort=combined'), null);
});

test('metric cohort selects the matching hosted snapshot and local ledger mode', () => {
  assert.equal(metricSnapshotKey('all'), 'metrics:all');
  assert.equal(metricSnapshotKey('recommendations'), 'metrics:recommendations');
  assert.deepEqual(metricLedgerArgs('all'), ['-m', 'sportsbet.ledger']);
  assert.deepEqual(metricLedgerArgs('recommendations'), [
    '-m', 'sportsbet.ledger', '--recommendations-only'
  ]);
});
