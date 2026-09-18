import {bestPicks,conservativeMargin} from './bestPicks.ts';
import type {EVSignal,PropType} from './types';
export const PROP_LABELS:Record<PropType,string>={points:'points',rebounds:'rebounds',assists:'assists',threes:'three-pointers',pra:'points + rebounds + assists',steals:'steals',blocks:'blocks',pass_yds:'passing yards',pass_tds:'passing touchdowns',rush_yds:'rushing yards',rec_yds:'receiving yards',receptions:'receptions'};
/** Revalidate at display/copy time; no stale or unapproved record can produce bet terms. */
export function pickTerms(value:EVSignal,now=Date.now()) {
  const signal=bestPicks([value],now)[0];
  if(!signal) return null;
  const netPayout=signal.american_odds<0 ? 100/-signal.american_odds : signal.american_odds/100;
  return {signal,pick:`${signal.direction==='over' ? 'Over' : 'Under'} ${signal.line} ${PROP_LABELS[signal.prop_type]}`,
    price:`${signal.american_odds>0 ? '+' : ''}${signal.american_odds}`,
    expectedPer100:100*signal.expected_return!,
    lowerBoundPer100:100*(signal.confidence_interval![0]*(netPayout+1)+(signal.push_probability ?? 0)-1),
    margin:conservativeMargin(signal)!,quoteAgeSeconds:Math.max(0,Math.floor((now-Date.parse(signal.snapped_at))/1000))};
}
