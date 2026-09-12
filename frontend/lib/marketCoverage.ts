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
