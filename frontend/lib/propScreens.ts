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

export function publicPropScreen(value: unknown, now=Date.now()) {
  const data=record(value);
  if (data.schema_version !== 1 || (data.sport !== 'nfl' && data.sport !== 'nba')
      || (data.status !== 'observed' && data.status !== 'degraded') || data.execution_ready !== false
      || !Array.isArray(data.comparisons)) throw new Error('Invalid prop screen');
  const coverage=record(data.coverage);
  const events=count(coverage.events), observed=count(coverage.observed_events);
  const unavailable=count(coverage.unavailable_events), positive=count(coverage.positive_gross_gaps);
  const sportsbook=count(coverage.sportsbook_gaps), kalshi=count(coverage.kalshi_sportsbook_gaps);
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
      const line=decimal(item.line), cost=decimal(item.gross_cost_to_one_dollar,0,1,true);
      const gap=decimal(item.gross_gap_to_one_dollar,0,1,true);
      const allowed=data.sport === 'nfl' ? ['pass_yds','rush_yds','rec_yds','receptions'] : ['points','rebounds','assists'];
      if (!allowed.includes(text(item.prop_type)) || Number(line)%1 !== .5
          || Math.abs(Number(legs[0].cost)+Number(legs[1].cost)-Number(cost)) > 1e-12
          || Math.abs(Number(cost)+Number(gap)-1) > 1e-12) throw new Error('Invalid prop screen');
      return {kind:item.kind,event_id:text(item.event_id), player:text(item.player), prop_type:item.prop_type as string,
        line, gross_cost_to_one_dollar:cost, gross_gap_to_one_dollar:gap, legs,
        limitations:item.reasons.map(text), status:'unverified', execution_ready:false};
    });
  if (!Number.isFinite(now)) throw new Error('Invalid prop screen');
  const age=(now-Date.parse(generated))/1000;
  const fresh=0 <= age && age <= 300 ? comparisons.filter(item => item.legs.every(
    leg => 0 <= (now-Date.parse(leg.observed_at))/1000 && (now-Date.parse(leg.observed_at))/1000 <= 300)) : [];
  return {
    sport:data.sport, generated_at:generated, status:fresh.length || (positive === 0 && age >= 0 && age <= 300)
      ? data.status : 'stale',
    coverage:{events, observed_events:observed, unavailable_events:unavailable,
      captured_positive_gross_gaps:positive, positive_gross_gaps:fresh.length,
      sportsbook_gaps:sportsbook, kalshi_sportsbook_gaps:kalshi},
    comparisons:fresh,
    execution_ready:false,
  };
}
