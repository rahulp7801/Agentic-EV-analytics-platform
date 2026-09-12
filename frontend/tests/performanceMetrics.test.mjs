import assert from 'node:assert/strict';
import test from 'node:test';

import { rateInterval } from '../lib/performanceMetrics.ts';

test('rate intervals format valid probability bounds without inventing missing values', () => {
  assert.equal(rateInterval({ interval: [0.094531, 0.905469] }, 'interval'), '9.5–90.5%');
  for (const value of [null, [0.2], [0.7, 0.3], [-0.1, 0.5], [0.2, 1.1], [0.2, NaN]]) {
    assert.equal(rateInterval({ interval: value }, 'interval'), 'Unavailable');
  }
});
