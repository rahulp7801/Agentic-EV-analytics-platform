import {publicPlayerProfile,publicSignal} from './signalMetrics.ts';
import type {EVSignal,Sport} from './types';

export type PickBoardRecord=EVSignal&{
  prediction_id:string;captured_at:string;lock_at:string;
  board_state:'recorded'|'locked'|'final';selection_policy_version:'pregame-t60-v1';
  result?:'win'|'loss'|'push'|'void'|'pending';result_verified?:boolean;
  actual_value?:number|null;settled_at?:string|null;
};
export type PickBoard={generated_at:string;lock_minutes:60;selection_policy_version:'pregame-t60-v1';
  current:PickBoardRecord[];history:PickBoardRecord[];
  summary:{current:number;settled:number;pending:number;wins:number;losses:number;pushes:number;verified_win_rate:number|null}};

const stamp=(value:unknown)=>typeof value==='string' && /([zZ]|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
const count=(value:unknown)=>Number.isSafeInteger(value) && Number(value)>=0 && Number(value)<=500;

function record(value:unknown,sport:Sport,profileValues:unknown,now:number,history:boolean,snapshotTime:number):PickBoardRecord|null {
  if(!value || typeof value!=='object' || Array.isArray(value)) return null;
  const raw=value as Record<string,unknown>,captured=Date.parse(String(raw.captured_at ?? ''));
  const lock=Date.parse(String(raw.lock_at ?? '')),start=Date.parse(String(raw.game_start_time ?? ''));
  if(!stamp(raw.captured_at) || !stamp(raw.lock_at) || raw.selection_policy_version!=='pregame-t60-v1'
    || raw.prediction_id!==raw.id || typeof raw.id!=='string' || raw.id.length!==64
    || !/^[a-f0-9]{64}$/.test(raw.id) || lock!==start-3600000 || captured>lock
    || captured>snapshotTime || Date.parse(String(raw.snapped_at))>captured
    || typeof raw.kelly_fraction!=='number' || raw.kelly_fraction>0.05
    || !['recorded','locked','final'].includes(String(raw.board_state))) return null;
  const signal=publicSignal(raw,captured);
  if(!signal || signal.sport!==sport || signal.gated || signal.kelly_fraction<=0) return null;
  let playerProfile=signal.player_profile;
  if(Array.isArray(profileValues) && profileValues.length<=500) {
    const matches=profileValues.map(item=>publicPlayerProfile(item,sport,signal.player,now)).filter(Boolean);
    if(matches.length===1) playerProfile=matches[0];
  }
  const result=raw.result;
  if(history) {
    if(raw.board_state!=='final' || start>snapshotTime || !['win','loss','push','void','pending'].includes(String(result))
      || typeof raw.result_verified!=='boolean' || (raw.result_verified!==(result!=='pending'))
      || (raw.result_verified && (typeof raw.actual_value!=='number' || !Number.isFinite(raw.actual_value) || !stamp(raw.settled_at)))
      || (!raw.result_verified && (raw.actual_value!==null || raw.settled_at!==null))) return null;
    if(raw.result_verified) {
      const actual=Number(raw.actual_value),settled=Date.parse(String(raw.settled_at));
      const reproduced=actual===signal.line ? 'push'
        : ((actual>signal.line)===(signal.direction==='over') ? 'win' : 'loss');
      if(result!==reproduced || settled<start || settled>snapshotTime) return null;
    }
  } else if(!['recorded','locked'].includes(String(raw.board_state)) || start<=snapshotTime
    || (raw.board_state==='recorded')!==(snapshotTime<lock)) return null;
  // Validate the publisher's state at publication time. Elapsed wall time is not
  // data corruption and cannot invalidate unrelated records on the same board.
  return {...signal,...(playerProfile ? {player_profile:playerProfile} : {}),
    prediction_id:raw.prediction_id as string,captured_at:raw.captured_at as string,lock_at:raw.lock_at as string,
    board_state:raw.board_state as PickBoardRecord['board_state'],selection_policy_version:'pregame-t60-v1',
    ...(history ? {result:result as PickBoardRecord['result'],result_verified:raw.result_verified as boolean,
      actual_value:raw.result_verified ? Number(raw.actual_value) : null,
      settled_at:raw.result_verified ? raw.settled_at as string : null} : {})};
}

export function publicPickBoard(value:unknown,profiles:unknown,sport:Sport,now=Date.now()):PickBoard {
  if(!value || typeof value!=='object' || Array.isArray(value)) throw new Error('Pick board unavailable');
  const board=value as Record<string,unknown>,summary=board.summary as Record<string,unknown>|undefined;
  const profileValues=(profiles as {profiles?:unknown}|null)?.profiles;
  if(board.schema_version!==1 || board.sport!==sport || !stamp(board.generated_at)
    || Date.parse(board.generated_at as string)>now+60000 || board.lock_minutes!==60
    || board.selection_policy_version!=='pregame-t60-v1' || !Array.isArray(board.current)
    || !Array.isArray(board.history) || board.current.length>100 || board.history.length>200 || !summary
    || !['current','settled','pending','wins','losses','pushes'].every(key=>count(summary[key]))) throw new Error('Invalid pick board');
  const snapshotTime=Date.parse(board.generated_at as string);
  const current=board.current.map(item=>record(item,sport,profileValues,now,false,snapshotTime)).filter(Boolean) as PickBoardRecord[];
  const history=board.history.map(item=>record(item,sport,profileValues,now,true,snapshotTime)).filter(Boolean) as PickBoardRecord[];
  const identities=[...current,...history].map(item=>item.id);
  const playerGames=[...current,...history].map(item=>`${item.game_id}\u0000${item.player}`);
  if(current.length!==board.current.length || history.length!==board.history.length
    || new Set(identities).size!==identities.length || new Set(playerGames).size!==playerGames.length
    || summary.current!==current.length || summary.settled!==history.filter(item=>item.result_verified).length
    || summary.pending!==history.filter(item=>!item.result_verified).length
    || summary.wins!==history.filter(item=>item.result==='win').length
    || summary.losses!==history.filter(item=>item.result==='loss').length
    || summary.pushes!==history.filter(item=>item.result==='push').length) throw new Error('Invalid pick board totals');
  const rate=summary.verified_win_rate;
  const decisions=Number(summary.wins)+Number(summary.losses);
  if((rate===null)!==(decisions===0) || (rate!==null && (typeof rate!=='number' || !Number.isFinite(rate) || rate<0 || rate>1
    || Math.abs(rate-(Number(summary.wins)/decisions))>1e-9))) throw new Error('Invalid pick board rate');
  // Never turn an old capture into a confirmed T-60 selection or invent a
  // settlement. Keep recorded labels until the publisher confirms the lock,
  // and remove started games from current output while awaiting its next update.
  const upcoming=current.filter(item=>Date.parse(item.game_start_time!)>now);
  return {generated_at:board.generated_at as string,lock_minutes:60,selection_policy_version:'pregame-t60-v1',
    current:upcoming,history,summary:{current:upcoming.length,settled:Number(summary.settled),pending:Number(summary.pending),
      wins:Number(summary.wins),losses:Number(summary.losses),pushes:Number(summary.pushes),
      verified_win_rate:rate as number|null}};
}
