import assert from 'node:assert/strict';
import test from 'node:test';
import { parseTerminalHash, terminalHash } from '../lib/terminalRoute.ts';

test('terminal locations round trip for shareable dashboard state', () => {
  assert.deepEqual(parseTerminalHash(terminalHash('nfl', 'backtest')), {
    sport: 'nfl',
    view: 'backtest',
  });
  assert.deepEqual(parseTerminalHash('#nba/props'), { sport: 'nba', view: 'props' });
  assert.deepEqual(parseTerminalHash('#cfb/dashboard'), { sport: 'cfb', view: 'dashboard' });
  assert.deepEqual(parseTerminalHash('#cfb/props'), { sport: 'cfb', view: 'props' });
  assert.deepEqual(parseTerminalHash('#cfb/arbitrage'), { sport: 'cfb', view: 'arbitrage' });
  assert.deepEqual(parseTerminalHash('#nfl/results'), { sport: 'nfl', view: 'results' });
  assert.deepEqual(parseTerminalHash('#cfb/results'), { sport: 'cfb', view: 'results' });
});

test('terminal locations reject unsupported leagues and views', () => {
  assert.equal(parseTerminalHash('#mlb/backtest'), null);
  assert.equal(parseTerminalHash('#nfl/admin'), null);
  assert.equal(parseTerminalHash('#cfb/gamelogs'), null);
  assert.equal(parseTerminalHash('#cfb/backtest'), null);
  assert.equal(parseTerminalHash(''), null);
});
