export interface MarketCoverage {
  discovered_games:number;
  attempted_games:number;
  observed_games:number;
  quoted_games:number;
  failed_games:number;
  event_failed_games?:number;
  market_failed_games?:number;
  sample_complete_games?:number;
}

export interface PropQuoteCoverage {
  prop_structured_quote_markets:number;
  prop_yes_ask_quote_markets?:number;
  prop_no_ask_quote_markets?:number;
  prop_two_sided_quote_markets?:number;
  prop_one_sided_quote_markets?:number;
  prop_unquoted_markets?:number;
}

export function sourceFailureText(reason:unknown):string|null {
  if (reason==='access_denied') return 'provider access denied';
  if (reason==='rate_limited') return 'provider rate limited';
  if (reason==='upstream_unavailable') return 'provider temporarily unavailable';
  if (reason==='request_rejected') return 'provider rejected the request';
  return null;
}

export function marketCoverageText(coverage:MarketCoverage):string {
  const {attempted_games:attempted,observed_games:observed,event_failed_games:eventFailed,
    market_failed_games:marketFailed,sample_complete_games:complete,quoted_games:quoted}=coverage;
  if ([attempted,observed,eventFailed,marketFailed,complete,quoted]
      .every(value=>Number.isSafeInteger(value))
      && eventFailed!==undefined && marketFailed!==undefined && complete!==undefined
      && attempted>=0 && observed>=0 && eventFailed>=0 && marketFailed>=0 && complete>=0
      && attempted===observed+eventFailed && observed===complete+marketFailed) {
    return `${observed}/${attempted} event records observed, ${eventFailed} event failures, `+
      `${complete} sampled games complete, ${marketFailed} with partial market failures, ${quoted} with quotes`;
  }
  return `${observed}/${coverage.discovered_games} discovered games inspected, `+
    `${quoted} with quotes, ${coverage.failed_games} with collection failures`;
}

export function propQuoteCoverageText(coverage:PropQuoteCoverage):string {
  const structured=coverage.prop_structured_quote_markets;
  const yes=coverage.prop_yes_ask_quote_markets;
  const no=coverage.prop_no_ask_quote_markets;
  const two=coverage.prop_two_sided_quote_markets;
  const one=coverage.prop_one_sided_quote_markets;
  const unquoted=coverage.prop_unquoted_markets;
  if ([structured,yes,no,two,one,unquoted].every(value=>Number.isSafeInteger(value))
      && yes!==undefined && no!==undefined && two!==undefined && one!==undefined && unquoted!==undefined
      && structured>=0 && yes>=0 && no>=0 && two>=0 && one>=0 && unquoted>=0
      && structured===two+one+unquoted && yes+no===2*two+one) {
    const rate=structured ? `${(100*two/structured).toFixed(1)}%` : 'n/a';
    return `${structured} structured top-of-book markets · ${two} two-sided (${rate}) · `+
      `${one} one-sided (${yes} YES asks, ${no} NO asks) · ${unquoted} without displayed asks`;
  }
  return `${structured} structured top-of-book markets (${two ?? 'unknown'} two-sided)`;
}
