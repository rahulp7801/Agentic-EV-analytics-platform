import {conservativeMargin,compareQuality} from './bestPicks.ts';
import type {PickBoardRecord} from './pickBoard.ts';

export const MAX_SLIP_LEGS=4;
export type SlipMode='balanced'|'conservative'|'diversified';

function exposure(record:PickBoardRecord) {
  return `${record.game_id}\u0000${record.player.trim().toLowerCase()}`;
}

function unique(records:PickBoardRecord[],now:number) {
  const seen=new Set<string>();
  return [...records].filter(record=>{
    const start=Date.parse(record.game_start_time ?? '');
    const selectable=!record.gated && record.kelly_fraction>0
      && Number.isFinite(start) && start>now && ['recorded','locked'].includes(record.board_state)
      && (conservativeMargin(record) ?? 0)>0;
    const key=exposure(record);
    if(!selectable || seen.has(key)) return false;
    seen.add(key);return true;
  });
}

function preferDistinctGames(records:PickBoardRecord[],maximum:number) {
  const chosen:PickBoardRecord[]=[],games=new Set<string>();
  for(const record of records) {
    if(chosen.length>=maximum) break;
    if(!games.has(record.game_id ?? '')) {chosen.push(record);games.add(record.game_id ?? '');}
  }
  for(const record of records) {
    if(chosen.length>=maximum) break;
    if(!chosen.some(item=>item.id===record.id)) chosen.push(record);
  }
  return chosen;
}

/** Select only already-approved board records; this function never creates a leg. */
export function assistedSlip(records:PickBoardRecord[],mode:SlipMode='balanced',now=Date.now(),maximum=MAX_SLIP_LEGS) {
  const limit=Math.max(1,Math.min(MAX_SLIP_LEGS,Math.floor(maximum)));
  const candidates=unique(records,now);
  if(mode==='conservative') return candidates.sort((a,b)=>b.true_prob-a.true_prob || compareQuality(a,b)).slice(0,Math.min(2,limit));
  const ranked=candidates.sort(compareQuality);
  return preferDistinctGames(ranked,mode==='balanced' ? Math.min(3,limit) : limit);
}

export function dependenceEnvelope(records:PickBoardRecord[]) {
  if(records.length<2 || records.some(record=>!Number.isFinite(record.true_prob)
    || record.true_prob<0 || record.true_prob>1)) return null;
  const probabilities=records.map(record=>record.true_prob);
  return {
    independent:probabilities.reduce((total,value)=>total*value,1),
    lower:Math.max(0,probabilities.reduce((total,value)=>total+value,0)-probabilities.length+1),
    upper:Math.min(...probabilities),
  };
}

export function slipWarnings(records:PickBoardRecord[]) {
  const warnings:string[]=[];
  const gameCounts=new Map<string,number>(),teamCounts=new Map<string,number>();
  for(const record of records) {
    const game=record.game_id ?? '';
    gameCounts.set(game,(gameCounts.get(game) ?? 0)+1);
    const team=`${game}\u0000${record.team || record.player_profile?.team || ''}`;
    teamCounts.set(team,(teamCounts.get(team) ?? 0)+1);
  }
  if([...gameCounts.values()].some(count=>count>1)) warnings.push('This slip has same-game legs. Their dependence has not been estimated, so the independence scenario may be misleading.');
  if([...teamCounts.entries()].some(([key,count])=>key.split('\u0000')[1] && count>1)) warnings.push('Multiple legs share a team and may react to the same game script or availability news.');
  if(records.some(record=>record.board_state==='recorded')) warnings.push('At least one price is recorded and must be repriced at the sportsbook before use.');
  if(records.some(record=>record.board_state==='locked')) warnings.push('At least one pick is frozen at the T-60 cutoff; its displayed price is historical.');
  return warnings;
}

export function assistantReasons(records:PickBoardRecord[],mode:SlipMode,edited=false) {
  if(!records.length) return ['No approved pregame pick is available for this league. The assistant will not manufacture a leg.'];
  const games=new Set(records.map(record=>record.game_id)).size;
  const lead=records[0],floor=conservativeMargin(lead);
  const intro=edited ? `This edited slip contains ${records.length} board-approved ${records.length===1?'leg':'legs'}.`
    : mode==='conservative'
    ? `Kept the slip to ${records.length} high-probability approved ${records.length===1?'leg':'legs'}.`
    : mode==='diversified'
      ? `Selected ${records.length} approved ${records.length===1?'leg':'legs'} across ${games} ${games===1?'game':'games'} where the board allowed it.`
      : `Ranked ${records.length} approved ${records.length===1?'leg':'legs'} by confidence-floor margin and preferred separate games.`;
  return [intro,`${lead.player} leads this build with a ${(lead.true_prob*100).toFixed(1)}% individual model estimate${floor===null?'':` and a +${(floor*100).toFixed(1)} point confidence-floor margin`}.`,
    'Roster, injury, and teammate context are screening evidence only; the published probabilities are not adjusted by an assistant.'];
}

export function expectedSlipReturn(envelope:ReturnType<typeof dependenceEnvelope>,grossPayout:number) {
  if(!envelope || !Number.isFinite(grossPayout) || grossPayout<=1 || grossPayout>100000) return null;
  return {independent:envelope.independent*grossPayout-1,
    lower:envelope.lower*grossPayout-1,upper:envelope.upper*grossPayout-1};
}
