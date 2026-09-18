'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {RefreshCw,ArrowUpRight} from 'lucide-react';
import {bestPicks} from '@/lib/bestPicks';
import {fetchForecasts} from '@/lib/fetchForecasts';
import {publicSignals,forecastWindow} from '@/lib/signalMetrics';
import {PROP_LABELS} from '@/lib/pickTerms';
import type {EVSignal,Sport} from '@/lib/types';
import PickCard from './PickCard';
import PredictionEvidence from './PredictionEvidence';
import PlayerPortrait from './PlayerPortrait';
import SlateReadiness from './SlateReadiness';
import ScanStatus from './ScanStatus';
import styles from './Overview.module.css';
export default function Overview({sport,onOpenMarkets,onOpenPlayers}:{sport:Sport;onOpenMarkets:()=>void;onOpenPlayers:(player?:string)=>void}) {
  const [candidates,setCandidates]=useState<EVSignal[]>([]),[forecasts,setForecasts]=useState<EVSignal[]>([]);
  const [total,setTotal]=useState(0),[complete,setComplete]=useState(true),[loading,setLoading]=useState(true),[refreshing,setRefreshing]=useState(false);
  const [errors,setErrors]=useState<string[]>([]),[now,setNow]=useState(0),[checked,setChecked]=useState(0);
  const [selected,setSelected]=useState<string|null>(null),[showSchedule,setShowSchedule]=useState(false),[showStatus,setShowStatus]=useState(false);
  const request=useRef<AbortController|null>(null),busy=useRef(false);
  const load=useCallback(async()=>{
    if(busy.current || document.visibilityState==='hidden') return;
    busy.current=true;setRefreshing(true);
    const controller=new AbortController();request.current=controller;
    const signal=AbortSignal.any([controller.signal,AbortSignal.timeout(15_000)]);
    try {
      const results=await Promise.allSettled([fetchForecasts(sport,signal,'qualified'),fetchForecasts(sport,signal,'library',fetch,100)]);
      if(controller.signal.aborted) return;
      const failures:string[]=[];
      if(results[0].status==='fulfilled' && results[0].value.complete) setCandidates(results[0].value.signals);
      else {setCandidates([]);failures.push('Current picks could not be fully checked.');}
      if(results[1].status==='fulfilled') {setForecasts(results[1].value.signals);setTotal(results[1].value.total_count);setComplete(results[1].value.complete);}
      else failures.push('Player history refresh is unavailable.');
      setErrors(failures);setChecked(Date.now());setNow(Date.now());setLoading(false);
    } finally {busy.current=false;if(!controller.signal.aborted)setRefreshing(false);}
  },[sport]);
  useEffect(()=>{
    const initial=window.setTimeout(()=>void load(),0),poll=window.setInterval(()=>void load(),60_000);
    const clock=window.setInterval(()=>setNow(Date.now()),5_000);
    document.addEventListener('visibilitychange',load);
    return()=>{request.current?.abort();window.clearTimeout(initial);window.clearInterval(poll);window.clearInterval(clock);document.removeEventListener('visibilitychange',load);};
  },[load]);
  const picks=bestPicks(candidates,now),records=publicSignals(forecasts,now).signals;
  const players=[...new Map(records.map(signal=>[signal.player,signal])).values()].slice(0,4);
  const explained=picks.find(signal=>signal.id===selected);
  return <section className={styles.overview} aria-label={`${sport.toUpperCase()} decision desk`}>
    <header className={styles.hero}><div><span className={styles.kicker}>{sport.toUpperCase()} / DECISION DESK</span><h1>Find your next pick.</h1><p>The exact selection, the observed price, and the evidence behind it.</p></div><div className={styles.heroActions}><button type="button" className={styles.refresh} disabled={refreshing} onClick={()=>void load()}><RefreshCw size={16} className={refreshing ? styles.spinning : undefined} />Refresh</button><span>{checked ? `Checked ${new Date(checked).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})}` : 'Checking published data'}</span></div></header>
    {errors.length>0 && <p className={styles.partialNotice} role="status">{errors.join(' ')} Refresh to try again.</p>}
    <section className={styles.shortlist} aria-label="Qualified picks"><div className={styles.comparisonHeading}><div><h2>Best available picks</h2><p>At most three. Fresh prices and every quality check must pass.</p></div><span className={styles.qualified}>{loading ? 'Checking' : `${picks.length} qualified`}</span></div>
      {loading ? <p className={styles.loading} role="status">Checking prices and model evidence...</p> : picks.length ? <div className={styles.betGrid}>{picks.map(pick=><PickCard key={pick.id} signal={pick} now={now} onExplain={()=>setSelected(pick.id)} />)}</div> : <div className={styles.noPicks}><h3>{errors[0]?.startsWith('Current picks') ? 'Picks are temporarily unavailable.' : 'No picks qualify right now.'}</h3><p>{errors[0]?.startsWith('Current picks') ? 'The current shortlist could not be verified.' : 'The published prices or model evidence do not clear every check. Historical forecasts remain useful for research, but are not current bets.'}</p><button type="button" className={styles.primary} onClick={()=>onOpenPlayers()}>Explore player forecasts <ArrowUpRight size={16} /></button></div>}
      {explained && <PredictionEvidence signal={explained} onClose={()=>setSelected(null)} />}
      <details className={styles.deskDetails}><summary>What makes a pick qualify?</summary><p>Explicit worker approval, a price no more than five minutes old, a future game, at least 20 prior observations with the correct game-date cutoff, supported uncertainty, current roster and injury screening, positive expected return and approved risk limits. Ranking uses the lower probability bound, not the largest headline estimate. Estimates do not guarantee profit. Recheck the exact line and odds at the sportsbook.</p></details>
    </section>
    <section className={styles.playersPanel} aria-label="Research forecasts"><div className={styles.comparisonHeading}><div><span>Research / not current bets</span><h2>Explore the players</h2></div><button type="button" onClick={()=>onOpenPlayers()}>All forecasts <ArrowUpRight size={15} /></button></div>
      <div className={styles.playersGrid}>{players.map(signal=><button type="button" key={signal.player} onClick={()=>onOpenPlayers(signal.player)}><PlayerPortrait signal={signal} /><strong>{signal.player}</strong><small>{signal.player_profile?.team ?? signal.availability?.team ?? sport.toUpperCase()}{signal.player_profile?.jersey ? ` / #${signal.player_profile.jersey}` : ''}{signal.player_profile?.position ? ` / ${signal.player_profile.position}` : ''}</small><span>{signal.direction==='over' ? 'Over' : 'Under'} {signal.line} {PROP_LABELS[signal.prop_type]}</span><small>{signal.sample_size} prior games / mean {signal.mean_stat?.toFixed(1) ?? 'not retained'}</small><small>{forecastWindow(signal,now)==='upcoming' ? 'Upcoming research forecast' : 'Past-game research record'}</small></button>)}</div>
      {!players.length && !loading && <p>{errors.some(error=>error.startsWith('Player')) ? 'Player records could not be refreshed.' : `No ${sport.toUpperCase()} forecasts are published. Try the other league or the landing-page demo.`}</p>}
      {players.length>0 && <p>{complete ? `${records.length} published research records.` : `Previewing ${records.length} of ${total} recent records. Open All forecasts for a larger research window.`} These cards are separate from the qualified shortlist.</p>}
    </section>
    <details className={styles.deskDetails} onToggle={event=>setShowSchedule(event.currentTarget.open)}><summary>Upcoming games and coverage</summary>{showSchedule && <SlateReadiness sport={sport} />}</details>
    <details className={styles.deskDetails} onToggle={event=>setShowStatus(event.currentTarget.open)}><summary>Data status and market sources</summary>{showStatus && <><ScanStatus /><p>Source availability and price comparisons are separate from qualified player picks.</p><button type="button" className={styles.refresh} onClick={onOpenMarkets}>Inspect market sources <ArrowUpRight size={15} /></button></>}</details>
  </section>;
}
