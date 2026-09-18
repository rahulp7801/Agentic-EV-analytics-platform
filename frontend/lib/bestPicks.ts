import {publicSignals} from './signalMetrics.ts';
import type {EVSignal} from './types';

export function conservativeMargin(signal:EVSignal):number|null {
  const interval=signal.confidence_interval;
  return interval && interval[0]<=signal.true_prob && signal.true_prob<=interval[1]
    && interval[1]<=1-(signal.push_probability ?? 0)+1e-12 ? interval[0]-signal.implied_prob : null;
}

export function compareQuality(a:EVSignal,b:EVSignal) {
  const left=conservativeMargin(a) ?? -Infinity,right=conservativeMargin(b) ?? -Infinity;
  return (left===right ? 0 : right-left) || (b.sample_size ?? 0)-(a.sample_size ?? 0) || a.id.localeCompare(b.id);
}

/** A small research shortlist; no quota and no manufactured quality score. */
export function bestPicks(value:unknown,now=Date.now()) {
  const candidates=publicSignals(value,now).signals.filter(signal=>!signal.gated
    // Decimal-backed 15pp edges can become 0.15000000000000002 in the browser.
    && signal.kelly_fraction>0 && signal.ev_pct<=.15+1e-12 && (signal.expected_return ?? 0)>0
    && (conservativeMargin(signal) ?? 0)>0);
  candidates.sort(compareQuality);
  const players=new Set<string>();
  return candidates.filter(signal=>{
    const key=`${signal.game_id}:${signal.player}`;
    if(players.has(key)) return false;
    players.add(key);return true;
  }).slice(0,3);
}
