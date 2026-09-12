type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid prop screen');
  return value as JsonRecord;
}

function text(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error('Invalid prop screen');
  return value;
}

function decimal(value: unknown, minimum=0, maximum=Number.POSITIVE_INFINITY, strict=false): string {
  const raw=text(value);
  const parsed=Number(raw);
  if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum
      || (strict && (parsed === minimum || parsed === maximum))) throw new Error('Invalid prop screen');
  return raw;
}

function timestamp(value: unknown): string {
  const raw=text(value);
  if (!/([zZ]|[+-]\d\d:\d\d)$/.test(raw) || !Number.isFinite(Date.parse(raw))) throw new Error('Invalid prop screen');
  return raw;
}

function count(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new Error('Invalid prop screen');
  return value as number;
}

function american(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || Math.abs(value) < 100
      || Math.abs(value) > 32767) throw new Error('Invalid prop screen');
  return value;
}

function sideFunnel(coverage: JsonRecord) {
  const keys=['kalshi_quotes','kalshi_exact_markets','kalshi_paired_sides',
    'kalshi_missing_ask_sides','kalshi_missing_sportsbook_sides','kalshi_observation_skew_sides'];
  const present=keys.filter(key=>coverage[key] !== undefined);
  if (present.length === 0) return undefined;
  if (present.length !== keys.length) throw new Error('Invalid prop screen');
  const result=Object.fromEntries(keys.map(key=>[key,count(coverage[key])])) as Record<string,number>;
  if (result.kalshi_exact_markets > result.kalshi_quotes
      || 2*result.kalshi_exact_markets !== result.kalshi_paired_sides
        +result.kalshi_missing_ask_sides+result.kalshi_missing_sportsbook_sides
        +result.kalshi_observation_skew_sides) throw new Error('Invalid prop screen');
  return result;
}

function leg(value: unknown) {
  const item=record(value);
  if (item.venue === 'kalshi') return {
    venue:'kalshi', ticker:text(item.ticker), side:text(item.side), cost:decimal(item.cost,0,1,true),
    displayed_size:decimal(item.displayed_size,0,Number.POSITIVE_INFINITY,true), observed_at:timestamp(item.observed_at),
  };
  if (item.venue === 'sportsbook') return {
    venue:'sportsbook', sportsbook:text(item.sportsbook), side:text(item.side),
    american_odds:american(item.american_odds), cost:decimal(item.cost,0,1,true),
    observed_at:timestamp(item.observed_at),
  };
  throw new Error('Invalid prop screen');
}

function feeScenarios(value: unknown, kalshiCost: string, sportsbookCost: string) {
  if (value === undefined) return undefined;
  const scenario=record(value), kalshi=record(scenario.kalshi_leg), combined=record(scenario.combined_cost);
  const result:Record<string,{kalshi_exchange_fee:string;combined_cost:string}>={};
  for (const label of ['direct','non_direct']) {
    const detail=record(kalshi[label]);
    const principal=decimal(detail.principal,0,1,true);
    const fee=decimal(detail.exchange_fee,0);
    const total=decimal(detail.total_cost,0);
    const cost=decimal(combined[label],0);
    if (Math.abs(Number(principal)-Number(kalshiCost))>1e-12
        || Math.abs(Number(total)-Number(principal)-Number(fee))>1e-12
        || Math.abs(Number(cost)-Number(total)-Number(sportsbookCost))>1e-12) {
      throw new Error('Invalid prop screen');
    }
    result[label]={kalshi_exchange_fee:fee,combined_cost:cost};
  }
  if (scenario.schedule_ref !== 'https://kalshi.com/regulatory/fee-schedule')
    throw new Error('Invalid prop screen');
  return {direct:result.direct,non_direct:result.non_direct,scope:text(scenario.scope)};
}

function settlementReview(value: unknown) {
  if (value === undefined) return {kalshi:{classified:false,participation:'unavailable',statistic:'unavailable',
    overtime:'unavailable',stat_corrections:'unavailable',stat_source:'unavailable'},
    sportsbook_rules:'unavailable',equivalence:'unverified'};
  const review=record(value), kalshi=record(review.kalshi);
  const participation=text(kalshi.participation), statistic=text(kalshi.statistic);
  const overtime=text(kalshi.overtime), corrections=text(kalshi.stat_corrections);
  const source=text(kalshi.stat_source);
  if (typeof kalshi.classified !== 'boolean'
      || !['active_no_snap_fair_market_price','unclassified'].includes(participation)
      || !['after_one_snap_recorded_stat','unclassified'].includes(statistic)
      || !['mentioned','unspecified','unavailable'].includes(overtime)
      || !['mentioned','unspecified','unavailable'].includes(corrections)
      || !['unspecified','unavailable'].includes(source)
      || kalshi.classified !== (participation !== 'unclassified' && statistic !== 'unclassified')
      || review.sportsbook_rules !== 'unavailable' || review.equivalence !== 'unverified') {
    throw new Error('Invalid prop screen');
  }
  return {kalshi:{classified:kalshi.classified,participation,statistic,overtime,
    stat_corrections:corrections,stat_source:source},sportsbook_rules:'unavailable',equivalence:'unverified'};
}

export function publicPropScreen(value: unknown, now=Date.now()) {
  const data=record(value);
  if (data.schema_version !== 1 || (data.sport !== 'nfl' && data.sport !== 'nba')
      || (data.status !== 'observed' && data.status !== 'degraded') || data.execution_ready !== false
      || !Array.isArray(data.comparisons)) throw new Error('Invalid prop screen');
  const coverage=record(data.coverage);
  const events=count(coverage.events), observed=count(coverage.observed_events);
  const unavailable=count(coverage.unavailable_events), positive=count(coverage.positive_gross_gaps);
  const sportsbook=count(coverage.sportsbook_gaps), kalshi=count(coverage.kalshi_sportsbook_gaps);
  const funnel=sideFunnel(coverage);
  const suppliedRuleCount=coverage.kalshi_rule_terms_classified === undefined ? undefined
    : count(coverage.kalshi_rule_terms_classified);
  const suppliedFeeCounts=coverage.kalshi_fee_modeled === undefined ? undefined : {
    modeled:count(coverage.kalshi_fee_modeled),direct:count(coverage.kalshi_direct_cost_below_one),
    nonDirect:count(coverage.kalshi_non_direct_cost_below_one),
  };
  if (observed+unavailable !== events || positive !== data.comparisons.length
      || positive !== sportsbook+kalshi) throw new Error('Invalid prop screen');
  const generated=timestamp(data.generated_at);
  const comparisons=data.comparisons.map(value => {
      const item=record(value);
      if ((item.kind !== 'kalshi_sportsbook_prop' && item.kind !== 'sportsbook_sportsbook_prop')
          || item.status !== 'unverified'
          || item.settlement_equivalent !== false || item.fee_adjusted_profit !== null
          || item.realized_profit !== null || item.execution_ready !== false
          || !Array.isArray(item.legs) || item.legs.length !== 2 || !Array.isArray(item.reasons)
          || item.reasons.length === 0) {
        throw new Error('Invalid prop screen');
      }
      const legs=item.legs.map(leg);
      const validKalshi=item.kind === 'kalshi_sportsbook_prop' && legs[0].venue === 'kalshi'
        && legs[1].venue === 'sportsbook' && ((legs[0].side === 'yes' && legs[1].side === 'Under')
          || (legs[0].side === 'no' && legs[1].side === 'Over'));
      const bookSides=new Set(legs.map(leg => leg.side));
      const validBooks=item.kind === 'sportsbook_sportsbook_prop' && legs.every(leg => leg.venue === 'sportsbook')
        && bookSides.size === 2 && bookSides.has('Over') && bookSides.has('Under') && new Set(legs.map(leg =>
          leg.venue === 'sportsbook' ? leg.sportsbook : '')).size === 2;
      if (!validKalshi && !validBooks) throw new Error('Invalid prop screen');
      for (const value of legs) if (value.venue === 'sportsbook') {
        const odds=value.american_odds;
        if (odds === undefined) throw new Error('Invalid prop screen');
        const expected=odds < 0 ? -odds/(100-odds) : 100/(100+odds);
        if (Math.abs(Number(value.cost)-expected)>1e-12) throw new Error('Invalid prop screen');
      }
      if (Math.abs(Date.parse(legs[0].observed_at)-Date.parse(legs[1].observed_at))>30_000)
        throw new Error('Invalid prop screen');
      const line=decimal(item.line), cost=decimal(item.gross_cost_to_one_dollar,0,1,true);
      const gap=decimal(item.gross_gap_to_one_dollar,0,1,true);
      const allowed=data.sport === 'nfl' ? ['pass_yds','rush_yds','rec_yds','receptions'] : ['points','rebounds','assists'];
      if (!allowed.includes(text(item.prop_type)) || Number(line)%1 !== .5
          || Math.abs(Number(legs[0].cost)+Number(legs[1].cost)-Number(cost)) > 1e-12
          || Math.abs(Number(cost)+Number(gap)-1) > 1e-12) throw new Error('Invalid prop screen');
      const modeled_fee_costs=validKalshi ? feeScenarios(item.exchange_fee_scenarios,
        legs[0].cost,legs[1].cost) : undefined;
      if (!validKalshi && (item.exchange_fee_scenarios !== undefined
          || item.settlement_review !== undefined)) throw new Error('Invalid prop screen');
      const settlement_review=validKalshi ? settlementReview(item.settlement_review)
        : settlementReview(undefined);
      return {kind:item.kind,event_id:text(item.event_id), player:text(item.player), prop_type:item.prop_type as string,
        line, gross_cost_to_one_dollar:cost, gross_gap_to_one_dollar:gap, legs,
        ...(modeled_fee_costs ? {modeled_fee_costs} : {}),settlement_review,
        limitations:item.reasons.map(text),
        status:'unverified', execution_ready:false};
    });
  const capturedClassified=comparisons.filter(item => item.settlement_review.kalshi.classified).length;
  const capturedModeled=comparisons.filter(item => 'modeled_fee_costs' in item);
  const capturedDirect=capturedModeled.filter(item => Number(item.modeled_fee_costs?.direct.combined_cost)<1).length;
  const capturedNonDirect=capturedModeled.filter(item => Number(item.modeled_fee_costs?.non_direct.combined_cost)<1).length;
  if (suppliedFeeCounts && (suppliedFeeCounts.modeled !== capturedModeled.length
      || suppliedFeeCounts.direct !== capturedDirect || suppliedFeeCounts.nonDirect !== capturedNonDirect)) {
    throw new Error('Invalid prop screen');
  }
  if (suppliedRuleCount !== undefined && suppliedRuleCount !== capturedClassified)
    throw new Error('Invalid prop screen');
  if (!Number.isFinite(now)) throw new Error('Invalid prop screen');
  const age=(now-Date.parse(generated))/1000;
  const fresh=0 <= age && age <= 300 ? comparisons.filter(item => item.legs.every(
    leg => 0 <= (now-Date.parse(leg.observed_at))/1000 && (now-Date.parse(leg.observed_at))/1000 <= 300)) : [];
  const freshSportsbook=fresh.filter(item => item.kind === 'sportsbook_sportsbook_prop').length;
  const freshKalshi=fresh.length-freshSportsbook;
  const freshModeled=fresh.filter(item => 'modeled_fee_costs' in item);
  return {
    sport:data.sport, generated_at:generated, status:fresh.length || (positive === 0 && age >= 0 && age <= 300)
      ? data.status : 'stale',
    coverage:{events, observed_events:observed, unavailable_events:unavailable,
      captured_positive_gross_gaps:positive, positive_gross_gaps:fresh.length,
      captured_sportsbook_gaps:sportsbook, captured_kalshi_sportsbook_gaps:kalshi,
      captured_kalshi_rule_terms_classified:capturedClassified,
      sportsbook_gaps:freshSportsbook, kalshi_sportsbook_gaps:freshKalshi,
      kalshi_rule_terms_classified:fresh.filter(item => item.settlement_review.kalshi.classified).length,
      captured_kalshi_fee_modeled:capturedModeled.length,
      captured_kalshi_direct_cost_below_one:capturedDirect,
      captured_kalshi_non_direct_cost_below_one:capturedNonDirect,
      kalshi_fee_modeled:freshModeled.length,
      kalshi_direct_cost_below_one:freshModeled.filter(item =>
        Number(item.modeled_fee_costs?.direct.combined_cost)<1).length,
      kalshi_non_direct_cost_below_one:freshModeled.filter(item =>
        Number(item.modeled_fee_costs?.non_direct.combined_cost)<1).length,
      ...(funnel ?? {})},
    comparisons:fresh,
    execution_ready:false,
  };
}
