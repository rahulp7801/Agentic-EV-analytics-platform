import type { Sport } from './types';

type Row = Record<string, unknown>;
const SCOPE = 'Observed prices only. Gross gaps exclude fees and full settlement states; they are not verified arbitrage or backtest returns.';
const FEE_SCOPE = 'One contract per Kalshi leg with modeled taker fees. Excludes sportsbook/FCM, funding and exceptional settlement charges. Not a fill or profit bound.';
const DEPTH_SCOPE = 'Hypothetical orders consuming displayed price levels. Actual fills, quote changes, limits and exceptional charges are not modeled. Not a fill or profit bound.';
const SOURCE_REASONS = new Set(['access_denied','rate_limited','upstream_unavailable','request_rejected']);
const COVERAGE_COUNTS = ['discovered_games','attempted_games','observed_games','quoted_games','failed_games',
  'event_failed_games','market_failed_games','sample_complete_games','omitted_markets','prop_open_events',
  'prop_fee_failures','prop_open_markets','prop_linked_events','prop_linked_markets','prop_series_expected',
  'prop_series_observed','prop_unquoted_markets','prop_no_ask_quote_markets','prop_fee_contexts_expected',
  'prop_fee_contexts_observed','prop_yes_ask_quote_markets','prop_one_sided_quote_markets',
  'prop_two_sided_quote_markets','prop_structured_quote_markets','prop_player_resolved_quote_markets'];

function row(value: unknown): Row {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid markets');
  return value as Row;
}
function count(value: unknown) {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new Error('Invalid markets');
  return value as number;
}
function text(value: unknown, maximum=200) {
  if (typeof value !== 'string' || !value.trim() || value.length > maximum || /[\u0000-\u001f]/.test(value)) throw new Error('Invalid markets');
  return value;
}
function decimal(value: unknown, minimum=0, maximum=Number.POSITIVE_INFINITY) {
  const raw=text(value,64), parsed=Number(raw);
  if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum) throw new Error('Invalid markets');
  return raw;
}
function timestamp(value: unknown) {
  const raw=text(value,64);
  if (!/([zZ]|[+-]\d\d:\d\d)$/.test(raw) || !Number.isFinite(Date.parse(raw))) throw new Error('Invalid markets');
  return raw;
}
function coverage(value: unknown) {
  const source=row(value), result:Record<string,number|boolean>={};
  for (const key of COVERAGE_COUNTS) if (source[key] !== undefined) result[key]=count(source[key]);
  for (const key of ['discovery_complete','prop_discovery_complete']) if (source[key] !== undefined) {
    if (typeof source[key] !== 'boolean') throw new Error('Invalid markets');
    result[key]=source[key] as boolean;
  }
  if (['discovered_games','attempted_games','observed_games','quoted_games','failed_games','omitted_markets','discovery_complete']
      .some(key=>result[key]===undefined)) throw new Error('Invalid markets');
  if (result.event_failed_games !== undefined && result.attempted_games !== (result.observed_games as number)+(result.event_failed_games as number)) throw new Error('Invalid markets');
  if (result.market_failed_games !== undefined && result.sample_complete_games !== undefined
      && result.observed_games !== (result.market_failed_games as number)+(result.sample_complete_games as number)) throw new Error('Invalid markets');
  if (result.prop_structured_quote_markets !== undefined && result.prop_two_sided_quote_markets !== undefined
      && result.prop_one_sided_quote_markets !== undefined && result.prop_unquoted_markets !== undefined
      && result.prop_structured_quote_markets !== (result.prop_two_sided_quote_markets as number)
        +(result.prop_one_sided_quote_markets as number)+(result.prop_unquoted_markets as number)) throw new Error('Invalid markets');
  return result;
}
function source(value: unknown) {
  const item=row(value), status=text(item.status,32);
  if (!['observed','degraded','unavailable','not_requested'].includes(status) || typeof item.partial_coverage !== 'boolean') throw new Error('Invalid markets');
  const reason=item.reason===undefined ? undefined : text(item.reason,64);
  if (reason && !SOURCE_REASONS.has(reason)) throw new Error('Invalid markets');
  return {status,count:count(item.count),partial_coverage:item.partial_coverage,
    ...(reason ? {reason} : {}),...(item.coverage===undefined ? {} : {coverage:coverage(item.coverage)})};
}
function compactCosts(value: unknown) {
  const costs=row(value); return {direct:decimal(costs.direct),non_direct:decimal(costs.non_direct)};
}
function comparison(value: unknown) {
  const item=row(value), kind=text(item.kind,32);
  if (!['sportsbooks','kalshi_pair','kalshi_sportsbook'].includes(kind) || item.status!=='unverified'
      || item.execution_ready!==false || item.realized_profit!==null || item.fee_adjusted_profit!==null
      || !Array.isArray(item.legs) || item.legs.length!==2 || !Array.isArray(item.reasons)
      || item.reasons.length===0 || item.reasons.length>4) throw new Error('Invalid markets');
  const legs=item.legs.map(value=>{const leg=row(value);return {book:text(leg.book,64),team:text(leg.team,100),
    cost:decimal(leg.cost,0,1),observed_at:timestamp(leg.observed_at)}});
  const gross=decimal(item.gross_cost,0,2), gap=decimal(item.gross_gap_to_one_dollar,-1,1);
  if (Math.abs(legs.reduce((sum,leg)=>sum+Number(leg.cost),0)-Number(gross))>1e-9
      || Math.abs(1-Number(gross)-Number(gap))>1e-9) throw new Error('Invalid markets');
  const fee=item.exchange_fee_scenarios===undefined ? undefined : row(item.exchange_fee_scenarios);
  const depth=item.depth_fee_scenarios===undefined ? undefined : row(item.depth_fee_scenarios);
  if ((fee || depth) && kind==='sportsbooks') throw new Error('Invalid markets');
  let feeScenario;
  if (fee) {
    if (fee.schedule_effective_date!=='2026-07-07') throw new Error('Invalid markets');
    feeScenario={combined_cost:compactCosts(fee.combined_cost),scope:FEE_SCOPE,schedule_effective_date:'2026-07-07'};
  }
  let depthScenario;
  if (depth) {
    if (!Array.isArray(depth.cases) || depth.cases.length>3) throw new Error('Invalid markets');
    depthScenario={cases:depth.cases.map(value=>{const entry=row(value);return {
      contracts_per_kalshi_leg:count(entry.contracts_per_kalshi_leg),combined_cost:compactCosts(entry.combined_cost)};}),scope:DEPTH_SCOPE};
  }
  return {identity:text(item.identity,200),kind,title:text(item.title,300),gross_cost:gross,
    gross_gap_to_one_dollar:gap,reasons:item.reasons.map(value=>text(value,300)),legs,
    ...(feeScenario ? {exchange_fee_scenarios:feeScenario} : {}),...(depthScenario ? {depth_fee_scenarios:depthScenario} : {})};
}

/** Validate and project the only market-observation shape allowed across the public API boundary. */
export function publicMarkets(value: unknown, expected: Sport) {
  const data=row(value);
  if (data.schema_version!==2 || data.sport!==expected || data.execution_ready!==false
      || data.realized_profit!==null || !Array.isArray(data.comparisons) || data.comparisons.length>200) throw new Error('Invalid markets');
  const sources=row(data.sources), resultSources:Record<string,ReturnType<typeof source>>={};
  for (const name of ['sportsbook','kalshi','prizepicks']) resultSources[name]=source(sources[name]);
  return {sport:expected,captured_at:timestamp(data.captured_at),scope:SCOPE,sources:resultSources,
    comparisons:data.comparisons.map(comparison)};
}
