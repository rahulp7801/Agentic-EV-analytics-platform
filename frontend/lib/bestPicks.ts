import {publicSignals} from './signalMetrics.ts';
import type {EVSignal} from './types';

export type PickGroup={pick:EVSignal;alternatives:EVSignal[]};

export function conservativeMargin(signal:EVSignal):number|null {
  const interval=signal.confidence_interval;
  return interval && interval[0]<=signal.true_prob && signal.true_prob<=interval[1]
    && interval[1]<=1-(signal.push_probability ?? 0)+1e-12 ? interval[0]-signal.implied_prob : null;
}

export function compareQuality(a:EVSignal,b:EVSignal) {
  const left=conservativeMargin(a) ?? -Infinity,right=conservativeMargin(b) ?? -Infinity;
  return (left===right ? 0 : right-left) || (b.sample_size ?? 0)-(a.sample_size ?? 0) || a.id.localeCompare(b.id);
}

function marketKey(signal:EVSignal) {
  return [signal.sport,signal.game_id ?? '',signal.player,signal.prop_type,signal.direction].join(':');
}

/** Collapse alternate thresholds for the same player market, preserving the supplied ranking. */
export function groupAlternateLines(signals:EVSignal[],alternativeLimit=10):PickGroup[] {
  const groups=new Map<string,PickGroup>(),seen=new Map<string,Set<string>>();
  for(const signal of signals) {
    const key=marketKey(signal),identity=`${signal.line}:${signal.sportsbook}:${signal.american_odds}`;
    const group=groups.get(key);
    if(!group) {groups.set(key,{pick:signal,alternatives:[]});seen.set(key,new Set([identity]));continue;}
    if(seen.get(key)?.has(identity) || group.alternatives.length>=alternativeLimit) continue;
    seen.get(key)?.add(identity);group.alternatives.push(signal);
  }
  return [...groups.values()];
}

function eligible(value:unknown,now:number) {
  return publicSignals(value,now).signals.filter(signal=>!signal.gated
    // Decimal-backed 15pp edges can become 0.15000000000000002 in the browser.
    && signal.kelly_fraction>0 && signal.ev_pct<=.15+1e-12 && (signal.expected_return ?? 0)>0
    && (conservativeMargin(signal) ?? 0)>0).sort(compareQuality);
}

/** At most one primary exposure per player/game, with bounded alternate lines for that market. */
export function bestPickGroups(value:unknown,now=Date.now(),maximum=3):PickGroup[] {
  const groups=groupAlternateLines(eligible(value,now));
  const players=new Set<string>();
  return groups.filter(group=>{
    const key=`${group.pick.game_id}:${group.pick.player}`;
    if(players.has(key)) return false;
    players.add(key);return true;
  }).slice(0,maximum);
}

/** Recent source-backed leans for an empty live board; every result remains explicitly gated. */
export function recentCandidateGroups(value:unknown,now=Date.now(),maximum=3):PickGroup[] {
  const ranked=publicSignals(value,now).signals.filter(signal=>signal.gated
    && Date.parse(signal.game_start_time ?? '')>now && Date.parse(signal.snapped_at)<=now+60000
    && signal.sample_size!==undefined && signal.sample_size>=20
    && signal.availability?.status==='observed' && signal.availability.roster_confirmed
    && signal.confidence_interval!==null && signal.expected_return!==null
    && (signal.expected_return ?? 0)>0 && signal.true_prob>signal.implied_prob
    && signal.ev_pct<=.15+1e-12).sort(compareQuality);
  const players=new Set<string>();
  return groupAlternateLines(ranked).filter(group=>{
    const key=`${group.pick.game_id}:${group.pick.player}`;
    if(players.has(key)) return false;
    players.add(key);return true;
  }).slice(0,maximum);
}

export function recentCandidateOptions(value:unknown,now=Date.now()) {
  return recentCandidateGroups(value,now).flatMap(group=>[group.pick,...group.alternatives]);
}

/** Transport primaries with their alternatives; consumers can render or collapse them. */
export function bestPickOptions(value:unknown,now=Date.now()) {
  return bestPickGroups(value,now).flatMap(group=>[group.pick,...group.alternatives]);
}

/** A small research shortlist; no quota and no manufactured quality score. */
export function bestPicks(value:unknown,now=Date.now()) {
  return bestPickGroups(value,now).map(group=>group.pick);
}
