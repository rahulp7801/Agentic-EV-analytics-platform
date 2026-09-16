import assert from 'node:assert/strict';
import test from 'node:test';
import { parseTerminalHash, terminalHash } from '../lib/terminalRoute.ts';

test('terminal locations round trip for shareable dashboard state', () => {
  assert.deepEqual(parseTerminalHash(terminalHash('nfl', 'backtest')), {
    sport: 'nfl',
    view: 'backtest',
  });
  assert.deepEqual(parseTerminalHash('#nba/props'), { sport: 'nba', view: 'props' });
});

test('terminal locations reject unsupported leagues and views', () => {
  assert.equal(parseTerminalHash('#mlb/backtest'), null);
  assert.equal(parseTerminalHash('#nfl/admin'), null);
  assert.equal(parseTerminalHash(''), null);
});
