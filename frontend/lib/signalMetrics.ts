import type {EVSignal,PropType,Sport} from './types';

/** Validate display metrics without inventing uncertainty or execution eligibility. */
export function expectedProfit(expectedReturn: unknown, stake: number): number | null {
  return typeof expectedReturn === 'number' && Number.isFinite(expectedReturn) && Number.isFinite(stake) && stake >= 0
    ? expectedReturn * stake : null;
}

export function signalMetrics(s: Record<string, unknown>, now = Date.now()) {
  const p = Number(s.true_prob), odds = Number(s.american_odds);
  const push = Number(s.push_probability ?? 0);
  const quoteTime = Date.parse(String(s.snapped_at ?? ''));
  const start = Date.parse(String(s.game_start_time ?? ''));
  const synthetic = String(s.sportsbook).toLowerCase() === 'prizepicks';
  const sample = Number(s.sample_size), kelly = Number(s.kelly_fraction);
  const valid = typeof s.true_prob === 'number' && typeof s.american_odds === 'number' && Number.isFinite(p) && p >= 0 && p <= 1 && Number.isFinite(push) && push >= 0 && p + push <= 1.000001
    && Number.isInteger(odds) && Math.abs(odds) >= 100 && (s.direction === 'over' || s.direction === 'under');
  const legacy = s.model_version !== 'empirical-jeffreys-v3';
  const stale = !Number.isFinite(quoteTime) || now - quoteTime > 300000 || quoteTime > now + 60000;
  const started = !Number.isFinite(start) || start <= now;
  const reason = !valid ? 'invalid_metrics' : legacy ? 'legacy_model' : synthetic ? 'synthetic_price'
    : stale ? 'stale_quote' : started ? 'missing_or_started_game' : (!Number.isFinite(sample) || sample < 20) ? 'insufficient_sample'
    : (!Number.isFinite(kelly) || kelly < 0 || kelly > 0.25) ? 'invalid_stake'
    : s.gated ? String(s.gate_reason ?? 'risk_gate') : null;
  const b = odds < 0 ? 100 / -odds : odds / 100;
  const ci = s.confidence_interval;
  const interval = !legacy && Array.isArray(ci) && ci.length === 2 && ci.every(x => typeof x === 'number' && Number.isFinite(x))
    && ci[0] >= 0 && ci[0] <= ci[1] && ci[1] <= 1 ? ci : null;
  const breakEven = (1 - push) / (1 + b);
  return {...s, implied_prob: valid && !synthetic ? breakEven : s.implied_prob,
    ev_pct: valid && !synthetic ? p - breakEven : s.ev_pct, expected_return: valid && !legacy && !synthetic ? p * b - (1 - p - push) : null,
    confidence_interval: interval, strength: 'unrated', gated: reason !== null, gate_reason: reason,
    kelly_fraction: reason ? 0 : s.kelly_fraction};
}

const SPORTS = new Set<Sport>(['nba','nfl']);
const PROPS = new Set<PropType>(['points','rebounds','assists','threes','pra','steals','blocks',
  'pass_yds','pass_tds','rush_yds','rec_yds','receptions']);

function finite(value:unknown):value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Return the only signal shape allowed across the public API boundary. */
export function publicSignal(value:unknown, now=Date.now()):EVSignal|null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const s=value as Record<string,unknown>;
  const sport=SPORTS.has(s.sport as Sport) ? s.sport as Sport : null;
  const prop=PROPS.has(s.prop_type as PropType) ? s.prop_type as PropType : null;
  const tradePlan=s.trade_plan;
  const flags=s.injury_flags;
  const mean=s.mean_stat;
  if (typeof s.id !== 'string' || !s.id || typeof s.player !== 'string' || !s.player.trim()
      || typeof s.team !== 'string' || typeof s.opponent !== 'string'
      || typeof s.home_team !== 'string' || !s.home_team || typeof s.away_team !== 'string' || !s.away_team
      || typeof s.game_id !== 'string' || !s.game_id || !sport || !prop
      || !finite(s.line) || Number(s.line)<0 || (s.direction !== 'over' && s.direction !== 'under')
      || typeof s.sportsbook !== 'string' || !s.sportsbook.trim() || s.sportsbook.toLowerCase()==='prizepicks'
      || typeof s.american_odds !== 'number' || !Number.isInteger(s.american_odds) || Math.abs(s.american_odds)<100
      || !finite(s.true_prob) || Number(s.true_prob)<0 || Number(s.true_prob)>1
      || !finite(s.push_probability) || Number(s.push_probability)<0
      || Number(s.true_prob)+Number(s.push_probability)>1.000001
      || typeof s.sample_size !== 'number' || !Number.isSafeInteger(s.sample_size) || s.sample_size<0
      || (mean !== null && !finite(mean)) || typeof s.model_version !== 'string' || !s.model_version
      || typeof s.snapped_at !== 'string' || !Number.isFinite(Date.parse(s.snapped_at))
      || typeof s.game_start_time !== 'string' || !Number.isFinite(Date.parse(s.game_start_time))
      || !Array.isArray(tradePlan) || tradePlan.length>3 || tradePlan.some(item=>typeof item !== 'string')
      || !flags || typeof flags !== 'object' || Array.isArray(flags)
      || Object.values(flags).some(item=>typeof item !== 'string')
      || typeof s.market_type !== 'string' || !s.market_type) return null;
  const metrics=signalMetrics(s,now);
  if (!finite(metrics.implied_prob) || !finite(metrics.ev_pct)
      || (metrics.expected_return !== null && !finite(metrics.expected_return))) return null;
  const gateReason=typeof metrics.gate_reason === 'string' ? metrics.gate_reason : undefined;
  const interval=metrics.confidence_interval as [number,number]|null;
  return {id:s.id,player:s.player,team:s.team,opponent:s.opponent,home_team:s.home_team,
    away_team:s.away_team,sport,prop_type:prop,line:s.line as number,direction:s.direction,
    true_prob:s.true_prob,implied_prob:metrics.implied_prob as number,ev_pct:metrics.ev_pct as number,
    expected_return:metrics.expected_return as number|null,push_probability:s.push_probability,
    confidence_interval:interval,model_version:s.model_version,game_start_time:s.game_start_time,
    kelly_fraction:metrics.kelly_fraction as number,american_odds:s.american_odds,
    sportsbook:s.sportsbook,trade_plan:[...tradePlan],injury_flags:{...flags} as Record<string,string>,
    market_type:s.market_type,snapped_at:s.snapped_at,strength:'unrated',
    gated:metrics.gated as boolean,...(gateReason ? {gate_reason:gateReason} : {}),
    sample_size:s.sample_size,mean_stat:mean as number|null,game_id:s.game_id};
}

export function publicSignals(value:unknown, now=Date.now()) {
  if (!Array.isArray(value)) throw new Error('Invalid signal collection');
  const signals:EVSignal[]=[];
  for (const item of value) {
    const signal=publicSignal(item,now);
    if (signal) signals.push(signal);
  }
  return {signals,invalid_signals:value.length-signals.length};
}

export function parlayScenario(probabilities: number[], grossPayout: number) {
  if (probabilities.length < 2 || !Number.isFinite(grossPayout) || grossPayout <= 1
      || probabilities.some(p => !Number.isFinite(p) || p < 0 || p > 1)) return null;
  const independent = probabilities.reduce((a, p) => a * p, 1);
  const lower = Math.max(0, probabilities.reduce((a, p) => a + p, 0) - probabilities.length + 1);
  const upper = Math.min(...probabilities);
  return {independent, lower, upper, expectedReturn: independent * grossPayout - 1};
}
