'use client';
import {useEffect,useState} from 'react';
import type {Sport} from '@/lib/types';
import type {slateReadiness,settlementProgress} from '@/lib/slateReadiness';
import styles from './Overview.module.css';
type Data={games:ReturnType<typeof slateReadiness>;partial:boolean;coverage_available:boolean;
  settlements:ReturnType<typeof settlementProgress>};
export default function SlateReadiness({sport}:{sport:Sport}) {
  const [data,setData]=useState<Data|null>(null),[error,setError]=useState(false);
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
  },[sport]);
  return <section className={styles.playersPanel} aria-label="Upcoming game readiness">
    <div className={styles.comparisonHeading}><div><span>Today and next seven days</span><h2>Current and upcoming slate</h2></div><small>{data ? data.games.length+' games' : 'Checking schedule'}</small></div>
    <p>In-progress games remain visible for coverage, but their picks lock exactly at kickoff. Pregame research capture covers the next 48 hours; a completed evaluation does not guarantee a qualified pick.</p>
    {error && <p role="status">Refresh unavailable. Previously loaded fixtures may be stale.</p>}
    {data?.partial && <p>Schedule coverage is partial; some dates could not be checked.</p>}
    {data && !data.coverage_available && <p>Worker coverage could not be checked. Fixtures remain visible.</p>}
    {data?.games.length===0 && <p>No upcoming {sport.toUpperCase()} games were observed in this schedule window.</p>}
    <div className={styles.slateGrid}>{data?.games.map(game=><article key={game.provider_event_id ?? game.home_name+game.game_time}>
      <small>{new Date(game.game_time).toLocaleString(undefined,{weekday:'long',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})}</small>
      <h3>{game.away_abbr} <span>at</span> {game.home_abbr}</h3><p>{game.away_name} · {game.home_name}</p>
      <strong>{game.state}</strong>
      {game.model_estimates!==null && <p>{game.model_estimates} of {game.selections} selections modeled{game.accepted_at_capture!==null ? ` · ${game.accepted_at_capture} accepted at capture` : ''}. Freshness is rechecked for the shortlist.</p>}
      {game.next_refresh_at && <p>Next permitted check: {new Date(game.next_refresh_at).toLocaleString()}. Scheduler timing can vary.</p>}
      {game.reasons.length>0 && <details><summary>Why selections were blocked</summary><ul>{game.reasons.map(reason=><li key={reason.label}>{reason.label}: {reason.count}</li>)}</ul></details>}
      {game.provider_event_id && <a href={`https://www.espn.com/${sport==='cfb'?'college-football':sport}/game/_/gameId/${encodeURIComponent(game.provider_event_id)}`} target="_blank" rel="noreferrer">View source game ↗</a>}
    </article>)}</div>
    <details className={styles.settlementDetails}><summary>How results get verified</summary><p>After final whistle, exact game and player identities must match a source-backed final stat. Missing or ambiguous evidence stays pending. All eligible forecasts and accepted recommendations are evaluated separately in Backtest lab; demo replays never enter those totals.</p>
      {data?.settlements ? <><p>Last check: {new Date(data.settlements.checked_at).toLocaleString()} · {data.settlements.stale ? 'Stale' : data.settlements.status}. {data.settlements.blocked}</p>
      {data.settlements.candidates!==null && <p>{data.settlements.candidates} records checked · {data.settlements.settled} verified in this pass · {data.settlements.pending} pending · {data.settlements.outside_schedule ?? 'Unknown count'} outside the checked schedule.</p>}
      <ul>{data.settlements.reasons.map(reason=><li key={reason.label}>{reason.label}: {reason.count}</li>)}</ul></> : <p>No settlement check is available here yet. This is not a zero-loss or zero-pending result.</p>}
    </details>
  </section>;
}
