import assert from 'node:assert/strict';
import test from 'node:test';
import { calculateKellyScenario } from '../lib/kellyScenario.ts';

test('Kelly scenario uses entered price for payout and fractional sizing', () => {
  const result = calculateKellyScenario({
    probability: .58,
    americanOdds: -110,
    kellyFraction: .25,
    bankroll: 1000,
  });

  assert.ok(result);
  assert.ok(Math.abs(result.impliedProbability - (110 / 210)) < 1e-12);
  assert.ok(Math.abs(result.fullKelly - .118) < 1e-12);
  assert.ok(Math.abs(result.sizedFraction - .0295) < 1e-12);
  assert.ok(Math.abs(result.stake - 29.5) < 1e-10);
  assert.ok(Math.abs(result.expectedReturn - .10727272727272727) < 1e-12);
  assert.equal(result.capped, false);
});

test('custom implied probability changes the displayed edge without changing payout math', () => {
  const result = calculateKellyScenario({
    probability: .58,
    americanOdds: -110,
    kellyFraction: .25,
    bankroll: 1000,
    impliedProbability: .55,
  });

  assert.ok(result);
  assert.ok(Math.abs(result.probabilityEdge - .03) < 1e-12);
  assert.ok(Math.abs(result.expectedReturn - .10727272727272727) < 1e-12);
});

test('Kelly scenario rejects invalid assumptions and caps extreme sizing', () => {
  assert.equal(calculateKellyScenario({ probability: 1, americanOdds: -110, kellyFraction: .25, bankroll: 1000 }), null);
  assert.equal(calculateKellyScenario({ probability: .58, americanOdds: -50, kellyFraction: .25, bankroll: 1000 }), null);
  assert.equal(calculateKellyScenario({ probability: .58, americanOdds: -110, kellyFraction: 1.1, bankroll: 1000 }), null);

  const capped = calculateKellyScenario({ probability: .95, americanOdds: 200, kellyFraction: 1, bankroll: 1000 });
  assert.ok(capped);
  assert.equal(capped.sizedFraction, .25);
  assert.equal(capped.stake, 250);
  assert.equal(capped.capped, true);
});
