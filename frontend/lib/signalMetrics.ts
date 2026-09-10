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
    && Number.isFinite(odds) && odds !== 0 && (s.direction === 'over' || s.direction === 'under');
  const legacy = s.model_version !== 'empirical-v2';
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

export function parlayScenario(probabilities: number[], grossPayout: number) {
  if (probabilities.length < 2 || !Number.isFinite(grossPayout) || grossPayout <= 1
      || probabilities.some(p => !Number.isFinite(p) || p < 0 || p > 1)) return null;
  const independent = probabilities.reduce((a, p) => a * p, 1);
  const lower = Math.max(0, probabilities.reduce((a, p) => a + p, 0) - probabilities.length + 1);
  const upper = Math.min(...probabilities);
  return {independent, lower, upper, expectedReturn: independent * grossPayout - 1};
}
