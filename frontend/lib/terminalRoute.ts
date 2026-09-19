import type { Sport } from './types';

export const TERMINAL_VIEWS = [
  'dashboard', 'props', 'gamelogs', 'arbitrage', 'backtest', 'parlay', 'kelly',
] as const;

export type TerminalView = typeof TERMINAL_VIEWS[number];

export function parseTerminalHash(hash: string): { sport: Sport; view: TerminalView } | null {
  const [sport, view] = hash.replace(/^#/, '').split('/');
  if ((sport !== 'nba' && sport !== 'nfl' && sport !== 'cfb')
      || !TERMINAL_VIEWS.includes(view as TerminalView) || (sport==='cfb' && view!=='arbitrage')) {
    return null;
  }
  return { sport, view: view as TerminalView };
}

export function terminalHash(sport: Sport, view: TerminalView) {
  return `#${sport}/${view}`;
}
