'use client';
import {useEffect,useState} from 'react';
import type {Sport} from '@/lib/types';
import type {slateReadiness,settlementProgress} from '@/lib/slateReadiness';
import styles from './Overview.module.css';
type Data={games:ReturnType<typeof slateReadiness>;partial:boolean;coverage_available:boolean;
  settlements:ReturnType<typeof settlementProgress>};
export default function SlateReadiness({sport,onOpenPlayers}:{sport:Sport;onOpenPlayers?:()=>void}) {
  const [data,setData]=useState<Data|null>(null),[error,setError]=useState(false);
  const [expanded,setExpanded]=useState(false),[retry,setRetry]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();let busy=false;
    async function load() {
      if(busy || document.visibilityState==='hidden') return;busy=true;
      try {
        const response=await fetch('/api/slate?sport='+sport,{cache:'no-store',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(12000)])});
        if(!response.ok) throw new Error('Unavailable');const body=await response.json();
        if(!Array.isArray(body.games) || body.games.length>100) throw new Error('Invalid slate');
        if(!controller.signal.aborted) {setData(body);setError(false);}
      } catch {if(!controller.signal.aborted) setError(true);}finally {busy=false;}
    }
    void load();const timer=setInterval(()=>void load(),60000);
    return ()=>{controller.abort();clearInterval(timer);};
  },[sport,retry]);
  return <section className={styles.playersPanel} aria-label="Upcoming game readiness">
    <div className={styles.comparisonHeading}><div><span>Today and next seven days</span><h2>Upcoming games</h2></div><small>{data ? data.games.length+' games' : 'Checking schedule'}</small></div>
    <p>Start with the matchup, then compare the player forecasts below. Research covers the next 48 hours; the recorded pick board freezes one hour before kickoff and live games cannot qualify.</p>
    {error && <p role="status">{data ? "Schedule refresh unavailable. Previously loaded fixtures may be stale." : "The schedule could not be loaded. This does not mean there are no games."} <button type="button" onClick={()=>setRetry(value=>value+1)}>Retry schedule</button></p>}
    {data?.partial && <p>Schedule coverage is partial; some dates could not be checked.</p>}
    {data && !data.coverage_available && <p>Worker coverage could not be checked. Fixtures remain visible.</p>}
    {data?.games.length===0 && <p>No upcoming {sport.toUpperCase()} games were observed in the next seven days. Switch leagues above to explore another schedule.</p>}
    <div className={styles.slateGrid}>{(expanded ? data?.games : data?.games.slice(0,3))?.map(game=><article key={game.provider_event_id ?? game.home_name+game.game_time}>
      <small>{new Date(game.game_time).toLocaleString(undefined,{weekday:'long',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})}</small>
      <h3>{game.away_abbr} <span>at</span> {game.home_abbr}</h3><p>{game.away_name} · {game.home_name}</p>
      <strong>{game.state}</strong>
      {game.model_estimates!==null && <p>{game.model_estimates} of {game.selections} selections modeled{game.accepted_at_capture!==null ? ` · ${game.accepted_at_capture} accepted at capture` : ''}. Freshness is rechecked for the shortlist.</p>}
      {game.checked_at && <p>Last game check: <time dateTime={game.checked_at}>{new Date(game.checked_at).toLocaleString()}</time>.</p>}
      {game.overdue_at ? <p>Quote check was due <time dateTime={game.overdue_at}>{new Date(game.overdue_at).toLocaleString()}</time>; no newer game check is recorded.</p>
        : game.next_refresh_at && <p>Next quote check due: <time dateTime={game.next_refresh_at}>{new Date(game.next_refresh_at).toLocaleString()}</time>. Collection depends on scheduler timing and available credits.</p>}
      {game.next_reserve_release_at && <p>Next reserve window: <time dateTime={game.next_reserve_release_at}>{new Date(game.next_reserve_release_at).toLocaleString()}</time>. Quote collection still depends on worker timing and available credits.</p>}
      {game.reasons.length>0 && <details><summary>Why selections were blocked</summary><ul>{game.reasons.map(reason=><li key={reason.label}>{reason.label}: {reason.count}</li>)}</ul></details>}
      {game.provider_event_id && <a href={`https://www.espn.com/${sport==='cfb'?'college-football':sport}/game/_/gameId/${encodeURIComponent(game.provider_event_id)}`} target="_blank" rel="noreferrer">View source game ↗</a>}
    </article>)}</div>
    <div className={styles.slateActions}>{data && data.games.length>3 && <button type="button" className={styles.reviewForecasts} aria-expanded={expanded} onClick={()=>setExpanded(value=>!value)}>{expanded ? "Show nearest games" : `Show all ${data.games.length} games`}</button>}
    {onOpenPlayers && data && data.games.length>0 && <button type="button" className={styles.reviewForecasts} onClick={onOpenPlayers}>Browse {sport.toUpperCase()} player forecasts</button>}</div>
    <details className={styles.settlementDetails}><summary>How results get verified</summary><p>After final whistle, exact game and player identities must match a source-backed final stat. Missing or ambiguous evidence stays pending. All eligible forecasts and accepted recommendations are evaluated separately in Backtest lab; demo replays never enter those totals.</p>
      {data?.settlements ? <><p>Last check: {new Date(data.settlements.checked_at).toLocaleString()} · {data.settlements.stale ? 'Stale' : data.settlements.status}. {data.settlements.blocked}</p>
      {data.settlements.candidates!==null && <p>{data.settlements.candidates} records checked · {data.settlements.settled} verified in this pass · {data.settlements.retained_accounting && `${data.settlements.retained_verified ?? 0} previously verified ? `}{data.settlements.pending} {data.settlements.retained_accounting ? 'pending' : 'not reverified in this pass'} · {data.settlements.outside_schedule ?? 'Unknown count'} outside the checked schedule.</p>}
      {!data.settlements.retained_accounting && <p>This older check does not distinguish previously verified results from unresolved records. See Backtest lab for verified outcome totals.</p>}
      {(data.settlements.retained_verified ?? 0)>0 && <p>Previously verified results retain their source evidence. Their latest source recheck was incomplete.</p>}
      <ul>{(data.settlements.retained_recheck_reasons ?? []).map(reason=><li key={reason.label}>Previously verified ? {reason.label.toLowerCase()}: {reason.count}</li>)}</ul>
      <ul>{data.settlements.reasons.map(reason=><li key={reason.label}>{reason.label}: {reason.count}</li>)}</ul></> : <p>No settlement check is available here yet. This is not a zero-loss or zero-pending result.</p>}
    </details>
  </section>;
}
