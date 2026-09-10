export type Sport = 'nba' | 'nfl';
export type PropType = 'points' | 'rebounds' | 'assists' | 'threes' | 'pra' | 'steals' | 'blocks' |
  'pass_yds' | 'pass_tds' | 'rush_yds' | 'rec_yds' | 'receptions';

export type SignalStrength = 'high' | 'medium' | 'low' | 'unrated';
export type Direction = 'over' | 'under';

export interface EVSignal {
  id: string;
  player: string;
  team: string;
  opponent: string;
  home_team?: string;
  away_team?: string;
  sport: Sport;
  prop_type: PropType;
  line: number;
  direction: Direction;
  true_prob: number;         // 0–1
  implied_prob: number;      // 0–1
  ev_pct: number;            // 0–1 (positive only)
  expected_return?: number | null;
  push_probability?: number;
  confidence_interval?: [number, number] | null;
  gate_reason?: string;
  data_source?: string;
  model_version?: string;
  game_start_time?: string;
  kelly_fraction: number;    // 0–0.25
  american_odds: number;
  pp_odds_tier?: 'standard' | 'demon'; // goblin (-110) filtered out at scan time
  sportsbook: string;
  trade_plan: string[]; // always 3 bullets from pipeline, string[] for flexibility
  injury_flags: Record<string, string>;
  market_type: string;
  snapped_at: string;
  strength: SignalStrength;
  // Extended fields from cache (not in EVSignal base type)
  gated?: boolean;
  sample_size?: number;
  mean_stat?: number;
  // Context signals from nba_context_producer
  opponent_def_rating?: number; // league avg = 115.0; higher = weaker defense
  rest_days?: number;           // 0 = back-to-back; 1+ = rest
  is_home?: boolean;
  // Multi-game cache field — set by scan_game_ev.py
  game_id?: string;
}

export interface GameLog {
  id: string;
  player: string;
  team: string;
  opponent: string;
  sport: Sport;
  date: string;
  home_away: 'home' | 'away';
  result?: 'W' | 'L';
  // NBA
  points?: number;
  rebounds?: number;
  assists?: number;
  threes?: number;
  steals?: number;
  blocks?: number;
  minutes?: number;
  // NFL
  pass_yds?: number;
  pass_tds?: number;
  rush_yds?: number;
  rec_yds?: number;
  receptions?: number;
}

export interface PropAnalysis {
  id: string;
  player: string;
  player_id: string;
  team: string;
  opponent: string;
  sport: Sport;
  prop_type: PropType;
  line: number;
  direction: Direction;
  model_prob: number;
  implied_prob: number;
  ev_pct: number;
  kelly_fraction: number;
  mean_stat: number;
  sample_size: number;
  confidence_interval: [number, number];
  sportsbook: string;
  american_odds: number;
}

export interface ArbitrageAlert {
  id: string;
  player: string;
  sport: Sport;
  prop_type: PropType;
  line: number;
  book_a: string;
  book_b: string;
  odds_a: number;
  odds_b: number;
  arb_pct: number;
  profit_per_100: number;
  detected_at: string;
  expires_estimate: string;
}

export interface MarketTicker {
  label: string;
  value: string;
  change: number; // + or -
  sport: Sport;
}
