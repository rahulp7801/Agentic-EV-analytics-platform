import assert from 'node:assert/strict';
import test from 'node:test';

import { metricInterval, rateInterval } from '../lib/performanceMetrics.ts';

test('rate intervals format valid probability bounds without inventing missing values', () => {
  assert.equal(rateInterval({ interval: [0.094531, 0.905469] }, 'interval'), '9.5–90.5%');
  for (const value of [null, [0.2], [0.7, 0.3], [-0.1, 0.5], [0.2, 1.1], [0.2, NaN]]) {
    assert.equal(rateInterval({ interval: value }, 'interval'), 'Unavailable');
  }
});

test('unbounded metric intervals format finite ranges without hiding uncertainty', () => {
  assert.equal(metricInterval({ interval: [-1, 1.837386] }, 'interval', true), '-100.0–183.7%');
  assert.equal(metricInterval({ interval: [0.076261, 0.443739] }, 'interval'), '0.076–0.444');
  for (const value of [null, [0.2], [0.7, 0.3], [0.2, NaN]]) {
    assert.equal(metricInterval({ interval: value }, 'interval'), 'Unavailable');
  }
});
