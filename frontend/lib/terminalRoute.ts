import type { Sport } from './types';

export const TERMINAL_VIEWS = [
  'dashboard', 'results', 'props', 'gamelogs', 'arbitrage', 'backtest', 'parlay', 'kelly',
] as const;

export type TerminalView = typeof TERMINAL_VIEWS[number];
const CFB_VIEWS=new Set<TerminalView>(['dashboard','results','props','arbitrage','parlay']);

export function parseTerminalHash(hash: string): { sport: Sport; view: TerminalView } | null {
  const [sport, view] = hash.replace(/^#/, '').split('/');
  if ((sport !== 'nba' && sport !== 'nfl' && sport !== 'cfb')
      || !TERMINAL_VIEWS.includes(view as TerminalView) || (sport==='cfb' && !CFB_VIEWS.has(view as TerminalView))) {
    return null;
  }
  return { sport, view: view as TerminalView };
}

export function terminalHash(sport: Sport, view: TerminalView) {
  return `#${sport}/${view}`;
}
