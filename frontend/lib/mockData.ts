import type { EVSignal, GameLog, PropAnalysis, ArbitrageAlert, MarketTicker } from './types';

export const EV_SIGNALS: EVSignal[] = [
  {
    id: 'ev-001', player: 'S. Gilgeous-Alexander', team: 'OKC', opponent: 'DAL',
    sport: 'nba', prop_type: 'points', line: 30.5, direction: 'over',
    true_prob: 0.638, implied_prob: 0.524, ev_pct: 0.114,
    kelly_fraction: 0.121, american_odds: -110, sportsbook: 'PrizePicks',
    trade_plan: ['+11.4% EV edge on points O/U market', 'Kelly sizing: 12.1% fractional stake (bankroll-relative, not flat)', 'No material injury flags for this game'],
    injury_flags: {}, market_type: 'player_prop', snapped_at: '2026-03-31T14:22:00Z', strength: 'high',
  },
  {
    id: 'ev-002', player: 'N. Jokic', team: 'DEN', opponent: 'LAL',
    sport: 'nba', prop_type: 'rebounds', line: 11.5, direction: 'over',
    true_prob: 0.591, implied_prob: 0.476, ev_pct: 0.115,
    kelly_fraction: 0.118, american_odds: -100, sportsbook: 'DraftKings',
    trade_plan: ['+11.5% EV edge on rebounds O/U market', 'Kelly sizing: 11.8% fractional stake (bankroll-relative, not flat)', 'No material injury flags for this game'],
    injury_flags: {}, market_type: 'player_prop', snapped_at: '2026-03-31T14:18:00Z', strength: 'high',
  },
  {
    id: 'ev-003', player: 'L. Doncic', team: 'DAL', opponent: 'OKC',
    sport: 'nba', prop_type: 'assists', line: 8.5, direction: 'over',
    true_prob: 0.562, implied_prob: 0.503, ev_pct: 0.059,
    kelly_fraction: 0.058, american_odds: -105, sportsbook: 'FanDuel',
    trade_plan: ['+5.9% EV edge on assists O/U market', 'Kelly sizing: 5.8% fractional stake (bankroll-relative, not flat)', 'No material injury flags for this game'],
    injury_flags: {}, market_type: 'player_prop', snapped_at: '2026-03-31T14:10:00Z', strength: 'medium',
  },
  {
    id: 'ev-004', player: 'T. Mahomes', team: 'KC', opponent: 'BUF',
    sport: 'nfl', prop_type: 'pass_yds', line: 289.5, direction: 'over',
    true_prob: 0.594, implied_prob: 0.481, ev_pct: 0.113,
    kelly_fraction: 0.114, american_odds: -100, sportsbook: 'BetMGM',
    trade_plan: ['+11.3% EV edge on pass_yds market', 'Kelly sizing: 11.4% fractional stake (bankroll-relative, not flat)', 'Material injury flags: T. Hill (Questionable)'],
    injury_flags: {'T. Hill': 'Questionable'}, market_type: 'player_prop', snapped_at: '2026-03-31T13:55:00Z', strength: 'high',
  },
  {
    id: 'ev-005', player: 'J. Morant', team: 'MEM', opponent: 'GSW',
    sport: 'nba', prop_type: 'points', line: 24.5, direction: 'under',
    true_prob: 0.571, implied_prob: 0.505, ev_pct: 0.066,
    kelly_fraction: 0.064, american_odds: -105, sportsbook: 'PrizePicks',
    trade_plan: ['+6.6% EV edge on points O/U market', 'Kelly sizing: 6.4% fractional stake (bankroll-relative, not flat)', 'Material injury flags: J. Morant (Day-to-Day)'],
    injury_flags: {'J. Morant': 'Day-to-Day'}, market_type: 'player_prop', snapped_at: '2026-03-31T13:40:00Z', strength: 'medium',
  },
  {
    id: 'ev-006', player: 'D. Henry', team: 'BAL', opponent: 'CIN',
    sport: 'nfl', prop_type: 'rush_yds', line: 94.5, direction: 'over',
    true_prob: 0.612, implied_prob: 0.509, ev_pct: 0.103,
    kelly_fraction: 0.104, american_odds: -105, sportsbook: 'Caesars',
    trade_plan: ['+10.3% EV edge on rush_yds market', 'Kelly sizing: 10.4% fractional stake (bankroll-relative, not flat)', 'No material injury flags for this game'],
    injury_flags: {}, market_type: 'player_prop', snapped_at: '2026-03-31T13:35:00Z', strength: 'high',
  },
  {
    id: 'ev-007', player: 'A. Edwards', team: 'MIN', opponent: 'BOS',
    sport: 'nba', prop_type: 'threes', line: 3.5, direction: 'over',
    true_prob: 0.537, implied_prob: 0.476, ev_pct: 0.061,
    kelly_fraction: 0.059, american_odds: -100, sportsbook: 'PrizePicks',
    trade_plan: ['+6.1% EV edge on threes O/U market', 'Kelly sizing: 5.9% fractional stake (bankroll-relative, not flat)', 'No material injury flags for this game'],
    injury_flags: {}, market_type: 'player_prop', snapped_at: '2026-03-31T13:20:00Z', strength: 'medium',
  },
  {
    id: 'ev-008', player: 'C. McCaffrey', team: 'SF', opponent: 'SEA',
    sport: 'nfl', prop_type: 'receptions', line: 5.5, direction: 'over',
    true_prob: 0.548, implied_prob: 0.490, ev_pct: 0.058,
    kelly_fraction: 0.057, american_odds: -105, sportsbook: 'DraftKings',
    trade_plan: ['+5.8% EV edge on receptions market', 'Kelly sizing: 5.7% fractional stake (bankroll-relative, not flat)', 'No material injury flags for this game'],
    injury_flags: {}, market_type: 'player_prop', snapped_at: '2026-03-31T13:05:00Z', strength: 'medium',
  },
];

export const GAME_LOGS: GameLog[] = [
  { id: 'gl-001', player: 'S. Gilgeous-Alexander', team: 'OKC', opponent: 'DAL', sport: 'nba', date: '2026-03-29', home_away: 'home', result: 'W', points: 34, rebounds: 5, assists: 7, threes: 2, steals: 2, blocks: 0, minutes: 36 },
  { id: 'gl-002', player: 'S. Gilgeous-Alexander', team: 'OKC', opponent: 'LAC', sport: 'nba', date: '2026-03-27', home_away: 'away', result: 'W', points: 28, rebounds: 4, assists: 5, threes: 1, steals: 3, blocks: 1, minutes: 35 },
  { id: 'gl-003', player: 'S. Gilgeous-Alexander', team: 'OKC', opponent: 'PHX', sport: 'nba', date: '2026-03-25', home_away: 'home', result: 'W', points: 41, rebounds: 6, assists: 9, threes: 3, steals: 1, blocks: 0, minutes: 38 },
  { id: 'gl-004', player: 'S. Gilgeous-Alexander', team: 'OKC', opponent: 'UTA', sport: 'nba', date: '2026-03-23', home_away: 'away', result: 'W', points: 33, rebounds: 3, assists: 6, threes: 2, steals: 2, blocks: 1, minutes: 34 },
  { id: 'gl-005', player: 'S. Gilgeous-Alexander', team: 'OKC', opponent: 'POR', sport: 'nba', date: '2026-03-21', home_away: 'home', result: 'W', points: 27, rebounds: 4, assists: 8, threes: 0, steals: 1, blocks: 0, minutes: 33 },
  { id: 'gl-006', player: 'S. Gilgeous-Alexander', team: 'OKC', opponent: 'MIN', sport: 'nba', date: '2026-03-19', home_away: 'away', result: 'L', points: 24, rebounds: 5, assists: 4, threes: 1, steals: 0, blocks: 0, minutes: 37 },
  { id: 'gl-007', player: 'N. Jokic', team: 'DEN', opponent: 'LAL', sport: 'nba', date: '2026-03-29', home_away: 'home', result: 'W', points: 26, rebounds: 14, assists: 10, threes: 1, steals: 1, blocks: 2, minutes: 35 },
  { id: 'gl-008', player: 'N. Jokic', team: 'DEN', opponent: 'LAC', sport: 'nba', date: '2026-03-27', home_away: 'away', result: 'L', points: 31, rebounds: 12, assists: 8, threes: 2, steals: 0, blocks: 1, minutes: 37 },
  { id: 'gl-009', player: 'T. Mahomes', team: 'KC', opponent: 'BUF', sport: 'nfl', date: '2026-01-18', home_away: 'home', result: 'W', pass_yds: 312, pass_tds: 3, rush_yds: 22 },
  { id: 'gl-010', player: 'T. Mahomes', team: 'KC', opponent: 'HOU', sport: 'nfl', date: '2026-01-11', home_away: 'home', result: 'W', pass_yds: 274, pass_tds: 2, rush_yds: 15 },
];

export const PROP_ANALYSES: PropAnalysis[] = [
  { id: 'pa-001', player: 'S. Gilgeous-Alexander', player_id: '1628983', team: 'OKC', opponent: 'DAL', sport: 'nba', prop_type: 'points', line: 30.5, direction: 'over', model_prob: 0.638, implied_prob: 0.524, ev_pct: 0.114, kelly_fraction: 0.121, mean_stat: 32.4, sample_size: 48, confidence_interval: [0.60, 0.68], sportsbook: 'PrizePicks', american_odds: -110 },
  { id: 'pa-002', player: 'N. Jokic', player_id: '203999', team: 'DEN', opponent: 'LAL', sport: 'nba', prop_type: 'rebounds', line: 11.5, direction: 'over', model_prob: 0.591, implied_prob: 0.476, ev_pct: 0.115, kelly_fraction: 0.118, mean_stat: 12.1, sample_size: 52, confidence_interval: [0.56, 0.62], sportsbook: 'DraftKings', american_odds: -100 },
  { id: 'pa-003', player: 'L. Doncic', player_id: '1629029', team: 'DAL', opponent: 'OKC', sport: 'nba', prop_type: 'assists', line: 8.5, direction: 'over', model_prob: 0.562, implied_prob: 0.503, ev_pct: 0.059, kelly_fraction: 0.058, mean_stat: 9.1, sample_size: 44, confidence_interval: [0.53, 0.59], sportsbook: 'FanDuel', american_odds: -105 },
  { id: 'pa-004', player: 'A. Edwards', player_id: '1630162', team: 'MIN', opponent: 'BOS', sport: 'nba', prop_type: 'threes', line: 3.5, direction: 'over', model_prob: 0.537, implied_prob: 0.476, ev_pct: 0.061, kelly_fraction: 0.059, mean_stat: 3.9, sample_size: 41, confidence_interval: [0.51, 0.57], sportsbook: 'PrizePicks', american_odds: -100 },
  { id: 'pa-005', player: 'T. Mahomes', player_id: 'maho-00001', team: 'KC', opponent: 'BUF', sport: 'nfl', prop_type: 'pass_yds', line: 289.5, direction: 'over', model_prob: 0.594, implied_prob: 0.481, ev_pct: 0.113, kelly_fraction: 0.114, mean_stat: 302.1, sample_size: 17, confidence_interval: [0.56, 0.63], sportsbook: 'BetMGM', american_odds: -100 },
  { id: 'pa-006', player: 'D. Henry', player_id: 'henr-00001', team: 'BAL', opponent: 'CIN', sport: 'nfl', prop_type: 'rush_yds', line: 94.5, direction: 'over', model_prob: 0.612, implied_prob: 0.509, ev_pct: 0.103, kelly_fraction: 0.104, mean_stat: 108.3, sample_size: 16, confidence_interval: [0.58, 0.65], sportsbook: 'Caesars', american_odds: -105 },
];

export const ARBITRAGE_ALERTS: ArbitrageAlert[] = [
  { id: 'arb-001', player: 'N. Jokic', sport: 'nba', prop_type: 'points', line: 25.5, book_a: 'FanDuel', book_b: 'DraftKings', odds_a: -108, odds_b: +105, arb_pct: 1.8, profit_per_100: 1.80, detected_at: '2026-03-31T14:25:00Z', expires_estimate: '2026-03-31T14:35:00Z' },
  { id: 'arb-002', player: 'L. Doncic', sport: 'nba', prop_type: 'threes', line: 2.5, book_a: 'BetMGM', book_b: 'Caesars', odds_a: -115, odds_b: +112, arb_pct: 2.1, profit_per_100: 2.10, detected_at: '2026-03-31T14:18:00Z', expires_estimate: '2026-03-31T14:28:00Z' },
  { id: 'arb-003', player: 'T. Mahomes', sport: 'nfl', prop_type: 'pass_tds', line: 2.5, book_a: 'PrizePicks', book_b: 'Underdog', odds_a: -120, odds_b: +118, arb_pct: 1.4, profit_per_100: 1.40, detected_at: '2026-03-31T14:05:00Z', expires_estimate: '2026-03-31T14:15:00Z' },
  { id: 'arb-004', player: 'A. Edwards', sport: 'nba', prop_type: 'rebounds', line: 5.5, book_a: 'Caesars', book_b: 'FanDuel', odds_a: -105, odds_b: +108, arb_pct: 2.7, profit_per_100: 2.70, detected_at: '2026-03-31T13:52:00Z', expires_estimate: '2026-03-31T14:02:00Z' },
];

export const MARKET_TICKER: MarketTicker[] = [
  { label: 'SGA PTS 30.5', value: 'O -110', change: 2.1, sport: 'nba' },
  { label: 'JOKIC REB 11.5', value: 'O -100', change: 1.8, sport: 'nba' },
  { label: 'MAHOMES YDS 289.5', value: 'O -105', change: -0.3, sport: 'nfl' },
  { label: 'HENRY RYD 94.5', value: 'O -105', change: 1.5, sport: 'nfl' },
  { label: 'DONCIC AST 8.5', value: 'O -105', change: 0.9, sport: 'nba' },
  { label: 'EDWARDS 3PM 3.5', value: 'O -100', change: 1.1, sport: 'nba' },
  { label: 'MCCAFFREY REC 5.5', value: 'O -105', change: 0.7, sport: 'nfl' },
  { label: 'MORANT PTS 24.5', value: 'U -105', change: -1.2, sport: 'nba' },
];

export const SUMMARY_STATS = {
  total_ev_signals: 144,
  high_confidence: 6,
  avg_ev_pct: 0.087,
  avg_kelly: 0.091,
  signals_today: 31,
  arb_opportunities: 4,
  books_monitored: 8,
  players_tracked: 287,
};
