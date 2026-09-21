'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {RefreshCw,ArrowUpRight} from 'lucide-react';
import {bestPickGroups,compareQuality,conservativeMargin,groupAlternateLines,recentCandidateGroups,type PickGroup} from '@/lib/bestPicks';
import {fetchForecasts} from '@/lib/fetchForecasts';
import {publicSignals,forecastWindow} from '@/lib/signalMetrics';
import {PROP_LABELS,latestRecordedQuote} from '@/lib/pickTerms';
import type {EVSignal,Sport} from '@/lib/types';
import type {PickBoard} from '@/lib/pickBoard';
import PickCard from './PickCard';
import PredictionEvidence from './PredictionEvidence';
import PlayerPortrait from './PlayerPortrait';
import SlateReadiness from './SlateReadiness';
import ScanStatus from './ScanStatus';
import styles from './Overview.module.css';
export default function Overview({sport,onOpenMarkets,onOpenPlayers}:{sport:Sport;onOpenMarkets:()=>void;onOpenPlayers:(player?:string)=>void}) {
  const [qualified,setQualified]=useState<EVSignal[]>([]),[watchlist,setWatchlist]=useState<EVSignal[]>([]),[forecasts,setForecasts]=useState<EVSignal[]>([]);
  const [board,setBoard]=useState<PickBoard|null>(null);
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
      const results=await Promise.allSettled([fetchForecasts(sport,signal,'qualified',fetch,1000,undefined,true),fetchForecasts(sport,signal,'candidates',fetch,1000),fetchForecasts(sport,signal,'library',fetch,36),fetch(`/api/picks?sport=${sport}`,{cache:'no-store',signal}).then(async response=>{if(!response.ok) throw new Error('Pick board unavailable');return response.json() as Promise<PickBoard>;})]);
      if(controller.signal.aborted) return;
      const failures:string[]=[];
      if(results[0].status==='fulfilled' && results[0].value.complete) setQualified(results[0].value.signals);
      else {setQualified([]);failures.push('Current picks could not be fully checked.');}
      if(results[1].status==='fulfilled') setWatchlist(results[1].value.signals);
      else {setWatchlist([]);failures.push('Recorded watchlist could not be refreshed.');}
      if(results[2].status==='fulfilled') {setForecasts(results[2].value.signals);setTotal(results[2].value.total_count);setComplete(results[2].value.complete);}
      else failures.push('Player history refresh is unavailable.');
      if(results[3].status==='fulfilled') setBoard(results[3].value); else {setBoard(null);failures.push('Recorded pick board could not be refreshed.');}
      setErrors(failures);setChecked(Date.now());setNow(Date.now());setLoading(false);
    } finally {busy.current=false;if(!controller.signal.aborted)setRefreshing(false);}
  },[sport]);
  useEffect(()=>{
    const initial=window.setTimeout(()=>void load(),0),poll=window.setInterval(()=>void load(),60_000);
    const clock=window.setInterval(()=>setNow(Date.now()),5_000);
    document.addEventListener('visibilitychange',load);
    return()=>{request.current?.abort();window.clearTimeout(initial);window.clearInterval(poll);window.clearInterval(clock);document.removeEventListener('visibilitychange',load);};
  },[load]);
  const liveGroups=bestPickGroups(qualified,now),retained=(board?.current ?? []).slice(0,3);
  const pickGroups=liveGroups.length ? liveGroups : retained.map(pick=>({pick,alternatives:[]}));
  const picks=pickGroups.map(group=>group.pick),records=publicSignals(forecasts,now).signals;
  const retainedBoard=!liveGroups.length && retained.length>0;
  const watchRecords=publicSignals(watchlist,now).signals;
  const previewMarkets=groupAlternateLines([...records].sort((a,b)=>Number(a.gated)-Number(b.gated) || compareQuality(a,b)));
  const recentGroups=recentCandidateGroups(watchRecords,now);
  const players=[...new Map(previewMarkets.map(group=>[group.pick.player,group.pick])).values()].slice(0,4);
  const explained=[...picks,...(board?.current ?? []),...watchRecords,...records].find(signal=>signal.id===selected);
  const latestQuote=latestRecordedQuote(watchRecords,now);
  const horizon=sport==='nfl' ? 'Tomorrow' : 'Next slate';
  return <section className={styles.overview} aria-label={`${sport.toUpperCase()} decision desk`}>
    <header className={styles.hero}><div><span className={styles.kicker}>{sport.toUpperCase()} / PREGAME PLAYER PROP DESK</span><h1>{horizon}, without the noise.</h1><p>Fresh qualified picks first, then the last worker-approved selections when prices need to be checked again. Picks freeze one hour before kickoff; in-game lines never enter the board.</p></div><div className={styles.heroActions}><button type="button" className={styles.refresh} disabled={refreshing} onClick={()=>void load()}><RefreshCw size={16} className={refreshing ? styles.spinning : undefined} />Refresh</button><span>{checked ? `Checked ${new Date(checked).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})}` : 'Checking published data'}</span></div></header>
    {errors.length>0 && !board?.current.length && <p className={styles.partialNotice} role="status">{errors.join(' ')} Refresh to try again.</p>}
    <section className={styles.shortlist} aria-label="Qualified picks"><div className={styles.comparisonHeading}><div><span>Live shortlist</span><h2>Best available picks</h2><p>One primary line per player. Fresh prices and every evidence gate must pass.</p></div><span className={styles.qualified}>{loading ? 'Checking' : `${picks.length} ${retainedBoard ? 'recorded' : 'qualified'}`}</span></div>
      {loading ? <PickSkeleton /> : picks.length ? <>{retainedBoard && <p className={styles.boardNotice}>No five-minute price is live. Showing the last worker-approved picks. Recorded picks require repricing; locked picks are frozen at the one-hour cutoff.</p>}<div className={styles.betGrid}>{pickGroups.map(group=><PickCard key={group.pick.id} signal={group.pick} alternatives={group.alternatives} now={now} onExplain={pick=>setSelected(pick.id)} />)}</div></> : <><div className={styles.noPicks}><span className={styles.noPicksStatus}>No approved pick recorded</span><h3>{errors[0]?.startsWith('Current picks') ? 'The live shortlist could not be checked.' : 'No line has cleared every gate yet.'}</h3><p>{errors[0]?.startsWith('Current picks') ? 'The evidence service did not return a complete shortlist, so the dashboard is withholding picks.' : 'The board records only source-backed recommendations that pass the model, uncertainty, roster, price and risk checks. It freezes the latest approved capture exactly one hour before kickoff and never admits an in-game line.'}</p>{latestQuote && <p>Newest research quote: <time dateTime={latestQuote.observed_at}>{new Date(latestQuote.observed_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})}</time>. {latestQuote.expired ? 'It is retained for research, but its price has expired.' : 'It still needs to clear every decision gate.'}</p>}</div>{recentGroups.length>0 && <section className={styles.recentShelf} aria-label={`${horizon} watchlist`}><div><span>{horizon} watchlist · reprice required</span><h3>Strongest recorded model leans</h3><p>These are real captured lines for future games, ranked by evidence. They are visible context, not current recommendations; confirm the latest line, price, roster, and injury report before any decision.</p></div><div className={styles.recentGrid}>{recentGroups.map(group=><RecentCandidateCard key={group.pick.id} group={group} now={now} onExplain={signal=>setSelected(signal.id)} />)}</div></section>}<button type="button" className={styles.reviewForecasts} onClick={()=>onOpenPlayers()}>Review all recorded forecasts <ArrowUpRight size={16} /></button></>}
      {explained && <PredictionEvidence signal={explained} onClose={()=>setSelected(null)} />}
      <details className={styles.deskDetails}><summary>What makes a pick qualify?</summary><p>Explicit worker approval, a price no more than five minutes old, a future game, at least 20 prior observations with the correct game-date cutoff, supported uncertainty, current roster and injury screening, positive expected return and approved risk limits. Ranking uses the lower probability bound, not the largest headline estimate. Estimates do not guarantee profit. Recheck the exact line and odds at the sportsbook.</p></details>
    </section>
    <section className={styles.playersPanel} aria-label="Research forecasts"><div className={styles.comparisonHeading}><div><span>Research / not current bets</span><h2>Explore the players</h2></div><button type="button" onClick={()=>onOpenPlayers()}>All forecasts <ArrowUpRight size={15} /></button></div>
      <div className={styles.playersGrid}>{players.map(signal=><button type="button" key={signal.player} onClick={()=>onOpenPlayers(signal.player)}><PlayerPortrait signal={signal} /><strong>{signal.player}</strong><small>{signal.player_profile?.team ?? signal.availability?.team ?? sport.toUpperCase()}{signal.player_profile?.jersey ? ` / #${signal.player_profile.jersey}` : ''}{signal.player_profile?.position ? ` / ${signal.player_profile.position}` : ''}</small><span>{signal.direction==='over' ? 'Over' : 'Under'} {signal.line} {PROP_LABELS[signal.prop_type]}</span><small>{signal.sample_size} prior games / mean {signal.mean_stat?.toFixed(1) ?? 'not retained'}</small><small>{forecastWindow(signal,now)==='upcoming' ? 'Upcoming research forecast' : 'Past-game research record'}</small></button>)}</div>
      {!players.length && !loading && <p>{errors.some(error=>error.startsWith('Player')) ? 'Player records could not be refreshed.' : `No ${sport.toUpperCase()} forecasts are published. Try the other league or the landing-page demo.`}</p>}
      {players.length>0 && <p>{complete ? `${records.length} published research records.` : `Previewing ${records.length} of ${total} recent records. Open All forecasts for a larger research window.`} These cards are separate from the qualified shortlist.</p>}
    </section>
    <details className={styles.deskDetails} onToggle={event=>setShowSchedule(event.currentTarget.open)}><summary>Upcoming games and coverage</summary>{showSchedule && <SlateReadiness sport={sport} />}</details>
    <details className={styles.deskDetails} onToggle={event=>setShowStatus(event.currentTarget.open)}><summary>Data status and market sources</summary>{showStatus && <><ScanStatus sport={sport} /><p>Source availability and price comparisons are separate from qualified player picks.</p><button type="button" className={styles.refresh} onClick={onOpenMarkets}>Inspect market sources <ArrowUpRight size={15} /></button></>}</details>
  </section>;
}

function RecentCandidateCard({group,now,onExplain}:{group:PickGroup;now:number;onExplain:(signal:EVSignal)=>void}) {
  const signal=group.pick,margin=conservativeMargin(signal),age=Math.max(0,now-Date.parse(signal.snapped_at));
  const ageText=age<3600000 ? `${Math.floor(age/60000)}m ago` : `${Math.floor(age/3600000)}h ago`;
  const availabilityAge=now-Date.parse(signal.availability?.captured_at ?? ''),availabilityExpired=!Number.isFinite(availabilityAge) || availabilityAge>3600000 || availabilityAge< -60000;
  const expired=age>300000,availabilityBlocked=availabilityExpired || signal.gate_reason==='player_availability_risk' || signal.gate_reason==='teammate_availability_unmodeled' || signal.gate_reason==='availability_unavailable';
  const status=expired && availabilityBlocked ? 'Expired evidence' : expired ? 'Expired price' : availabilityBlocked ? 'Availability block' : 'Blocked estimate';
  const pick=`${signal.direction==='over' ? 'Over' : 'Under'} ${signal.line} ${PROP_LABELS[signal.prop_type]}`;
  return <article className={styles.recentCard}><header><PlayerPortrait signal={signal} /><div><h4>{signal.player}</h4><small>{signal.player_profile?.team ?? signal.availability?.team ?? signal.sport.toUpperCase()}{signal.player_profile?.jersey ? ` / #${signal.player_profile.jersey}` : ''}{signal.player_profile?.position ? ` / ${signal.player_profile.position}` : ''}</small></div><span>{status}</span></header><h5>{pick}</h5><p><strong>{signal.sportsbook}</strong> {signal.american_odds>0?'+':''}{signal.american_odds} / observed {ageText}</p><dl><div><dt>Model</dt><dd>{(signal.true_prob*100).toFixed(1)}%</dd></div><div><dt>Break-even</dt><dd>{(signal.implied_prob*100).toFixed(1)}%</dd></div><div><dt>Point edge</dt><dd>+{(signal.ev_pct*100).toFixed(1)}pp</dd></div><div><dt>Confidence floor</dt><dd className={margin!==null && margin>0 ? styles.positiveFloor : styles.blockedFloor}>{margin===null ? 'Unavailable' : `${margin>0?'+':''}${(margin*100).toFixed(1)}pp`}</dd></div></dl><p className={styles.recentReason}>This is the latest recorded lean, not a current bet. {expired ? 'The price expired' : 'The price did not clear every live gate'}{availabilityBlocked ? '; roster and injury evidence also needs a fresh check' : ''}{margin!==null && margin<=0 ? '; its confidence floor did not clear break-even' : ''}.</p>{group.alternatives.length>0 && <details className={styles.recentAlternatives}><summary>{group.alternatives.length} other recorded {group.alternatives.length===1?'line':'lines'}</summary><div>{group.alternatives.map(option=><button type="button" key={option.id} onClick={()=>onExplain(option)}><span>{option.direction==='over'?'Over':'Under'} {option.line}</span><small>{option.sportsbook} / {option.american_odds>0?'+':''}{option.american_odds}</small></button>)}</div></details>}<button type="button" className={styles.evidenceButton} onClick={()=>onExplain(signal)}>Inspect evidence</button></article>;
}

function PickSkeleton() {
  return <div className={styles.skeletonGrid} role="status" aria-label="Checking prices and model evidence">{[0,1,2].map(item=><div className={styles.skeletonCard} key={item} aria-hidden="true"><span className={styles.skeletonAvatar} /><span className={styles.skeletonLine} /><span className={styles.skeletonLineShort} /><span className={styles.skeletonBlock} /><span className={styles.skeletonLine} /></div>)}</div>;
}
