'use client';
import {useState} from 'react';
import type {EVSignal} from '@/lib/types';
import type {PickBoardRecord} from '@/lib/pickBoard';
import {pickTerms,sportsbookLabel} from '@/lib/pickTerms';
import PlayerPortrait from './PlayerPortrait';
import styles from './Overview.module.css';
export default function PickCard({signal,alternatives=[],now,onExplain}:{signal:EVSignal;alternatives?:EVSignal[];now:number;onExplain:(signal:EVSignal)=>void}) {
  const [notice,setNotice]=useState('');
  const board=signal as PickBoardRecord,retained=board.board_state==='recorded' || board.board_state==='locked';
  const terms=pickTerms(signal,retained ? Date.parse(board.captured_at) : now);
  if(!terms) return null;
  const pick=terms.signal;
  async function copy() {
    const current=pickTerms(signal,retained ? Date.parse(board.captured_at) : Date.now());
    if(!current) {setNotice('This price expired. Refresh for current picks.');return;}
    try {
      await navigator.clipboard.writeText(`${pick.player}: ${current.pick} | ${pick.sportsbook} ${current.price} | ${pick.home_team} vs ${pick.away_team} | Starts ${pick.game_start_time} | Price observed ${pick.snapped_at}. Recheck the exact line and odds before placing any bet.`);
      setNotice('Copied. Recheck the exact line and price with the book.');
    } catch {setNotice('Copy is unavailable. The exact pick and price are shown above.');}
  }
  return <article className={styles.betCard} aria-label={`${pick.player} ${retained ? 'recorded' : 'qualified'} pick`}>
    <header><PlayerPortrait signal={pick} /><div><h3>{pick.player}</h3><p>{pick.player_profile?.team ?? pick.availability?.team}{pick.player_profile?.jersey ? ` / #${pick.player_profile.jersey}` : ''}{pick.player_profile?.position ? ` / ${pick.player_profile.position}` : ''}</p></div><span className={styles.qualified}>{board.board_state==='locked' ? 'Locked T−60' : board.board_state==='recorded' ? 'Recorded / reprice' : 'Live qualified'}</span></header>
    <h4>{terms.pick}</h4><div className={styles.betPrice}><strong>{sportsbookLabel(pick.sportsbook)}</strong><b>{terms.price}</b></div>
    <p>{pick.home_team} vs {pick.away_team}<br />{new Date(pick.game_start_time!).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})}</p>
    <dl className={styles.betMetrics}><div><dt>Model win probability</dt><dd>{(pick.true_prob*100).toFixed(1)}%</dd></div><div><dt>Price break-even</dt><dd>{(pick.implied_prob*100).toFixed(1)}%</dd></div><div><dt>Expected net per $100</dt><dd>+${terms.expectedPer100.toFixed(2)}</dd></div></dl>
    <p className={styles.betReason}>{pick.sample_size} prior games{pick.mean_stat!==null && pick.mean_stat!==undefined ? ` / historical mean ${pick.mean_stat.toFixed(1)}` : ''}. Even the reported lower probability bound clears this price by {(terms.margin*100).toFixed(1)} percentage points.</p>
    <small>{retained ? `Recorded ${new Date(board.captured_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})}. ${board.board_state==='locked' ? 'The pick is frozen; the displayed price is historical.' : 'Recheck the current price before acting.'}` : `Price observed ${terms.quoteAgeSeconds}s ago.`} Estimated return is uncertain, not a payout promise.</small>
    {alternatives.length>0 && <details className={styles.altLines}><summary>{alternatives.length} other observed {alternatives.length===1 ? 'line' : 'lines'}</summary><div>{alternatives.map(alternative=>{const option=pickTerms(alternative,now);return option ? <article key={alternative.id}><div><strong>{option.pick}</strong><span>{alternative.sportsbook} / {option.price}</span></div><div><span>{(alternative.true_prob*100).toFixed(1)}% model</span><button type="button" onClick={()=>onExplain(alternative)}>Evidence</button></div></article> : null;})}</div></details>}
    <div className={styles.betActions}><button type="button" onClick={()=>onExplain(pick)}>Why this pick</button><button type="button" onClick={()=>void copy()}>Copy exact pick</button></div>
    <p className={styles.copyNotice} role="status">{notice}</p>
  </article>;
}
