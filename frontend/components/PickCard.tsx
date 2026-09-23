'use client';
import {useState} from 'react';
import {ArrowUpRight,Check} from 'lucide-react';
import type {EVSignal} from '@/lib/types';
import type {PickBoardRecord} from '@/lib/pickBoard';
import {pickTerms,sportsbookLabel} from '@/lib/pickTerms';
import {pickCardPresentation} from '@/lib/pickPresentation';
import {pickContext} from '@/lib/pickContext';
import PlayerPortrait from './PlayerPortrait';
import styles from './Overview.module.css';

export default function PickCard({signal,alternatives=[],now,rank,onExplain,onOpenMarkets}:{
  signal:EVSignal;alternatives?:EVSignal[];now:number;rank:number;
  onExplain:(signal:EVSignal)=>void;onOpenMarkets:()=>void;
}) {
  const [notice,setNotice]=useState('');
  const board=signal as PickBoardRecord,presentation=pickCardPresentation(board,rank),retained=!presentation.actionable;
  const terms=pickTerms(signal,retained ? Date.parse(board.captured_at) : now);
  if(!terms) return null;
  const pick=terms.signal,[direction,line,...prop]=terms.pick.split(' '),context=pickContext(pick);

  async function copy() {
    const current=pickTerms(signal,Date.now());
    if(!current) {setNotice('This price expired. Refresh for current picks.');return;}
    try {
      await navigator.clipboard.writeText(`${pick.player}: ${current.pick} | ${pick.sportsbook} ${current.price} | ${pick.home_team} vs ${pick.away_team} | Starts ${pick.game_start_time} | Price observed ${pick.snapped_at}. Recheck the exact line and odds before placing any bet.`);
      setNotice('Copied. Recheck the exact line and price with the book.');
    } catch {setNotice('Copy is unavailable. The exact pick and price are shown above.');}
  }

  return <article className={`${styles.betCard} ${styles.pickEnter}`} data-state={presentation.state} data-rank={rank}
    aria-label={`${pick.player} ${presentation.state} pick`}>
    <div className={styles.pickRank}><span>{presentation.rankLabel}</span><strong>{presentation.status}</strong></div>
    <div className={styles.pickCall}><span>Suggested pick</span><h4><strong>{direction} {line}</strong><small>{prop.join(' ')}</small></h4></div>
    <header><PlayerPortrait signal={pick} /><div><h3>{pick.player}</h3><p>{pick.player_profile?.team ?? pick.availability?.team}{pick.player_profile?.jersey ? ` · #${pick.player_profile.jersey}` : ''}{pick.player_profile?.position ? ` · ${pick.player_profile.position}` : ''}</p></div></header>
    <div className={styles.betPrice}><span><small>{presentation.priceLabel}</small><strong>{sportsbookLabel(pick.sportsbook)}</strong></span><b>{terms.price}</b></div>
    <p className={styles.gameLine}>{pick.home_team} vs {pick.away_team}<br /><time dateTime={pick.game_start_time}>{new Date(pick.game_start_time!).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})}</time></p>
    <dl className={styles.betMetrics}><div><dt>Model probability</dt><dd>{(pick.true_prob*100).toFixed(1)}%</dd></div><div><dt>Break-even</dt><dd>{(pick.implied_prob*100).toFixed(1)}%</dd></div><div><dt>{presentation.returnLabel}</dt><dd>+${terms.expectedPer100.toFixed(2)}</dd></div></dl>
    <p className={styles.betReason}>{pick.sample_size} prior games{pick.mean_stat!==null && pick.mean_stat!==undefined ? ` · historical mean ${pick.mean_stat.toFixed(1)}` : ''}. The reported confidence floor clears this price by {(terms.margin*100).toFixed(1)} percentage points.</p>
    <section className={styles.betContext} aria-label="Captured pick context"><strong>Context checked</strong><p>{context.player}</p><p>{context.reports}</p><small>{context.detail}</small></section>
    <small className={styles.priceNote}>{retained ? `${presentation.priceLabel} captured ${new Date(board.captured_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})}. ${presentation.state==='locked' ? 'Terms are frozen under the one-hour policy.' : 'The current market may differ.'}` : `Price observed ${terms.quoteAgeSeconds}s ago.`} A positive model estimate is not a proven betting edge.</small>
    {alternatives.length>0 && <details className={styles.altLines}><summary>{alternatives.length} other observed {alternatives.length===1 ? 'line' : 'lines'}</summary><div>{alternatives.map(alternative=>{const option=pickTerms(alternative,now);return option ? <article key={alternative.id}><div><strong>{option.pick}</strong><span>{sportsbookLabel(alternative.sportsbook)} · {option.price}</span></div><div><span>{(alternative.true_prob*100).toFixed(1)}% model</span><button type="button" onClick={()=>onExplain(alternative)}>Evidence</button></div></article> : null;})}</div></details>}
    <div className={styles.betActions}><button type="button" onClick={()=>onExplain(pick)}>Inspect evidence</button>{presentation.actionable ? <button type="button" onClick={()=>void copy()}>{notice.startsWith('Copied') ? <Check size={14}/> : null}Copy current pick</button> : <button type="button" onClick={onOpenMarkets}>Check current markets <ArrowUpRight size={14}/></button>}</div>
    <p className={styles.copyNotice} role="status">{notice}</p>
  </article>;
}
