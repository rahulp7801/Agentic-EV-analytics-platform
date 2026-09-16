'use client';
import {useEffect,useState} from 'react';
import type {EVSignal} from '@/lib/types';
import {forecastHistory,historyCutoff} from '@/lib/forecastHistory';
import styles from './ResearchViews.module.css';

export default function PlayerHistory({signal}:{signal:EVSignal}) {
  const [logs,setLogs]=useState<unknown>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [count,setCount]=useState(20);
  const {sport,player}=signal;
  let cutoff:string|undefined;
  try {cutoff=historyCutoff(signal);} catch { /* Older forecasts may lack timing evidence. */ }
  useEffect(()=>{
    const controller=new AbortController();
    const timer=window.setTimeout(()=>{
      if(!cutoff) {setError('This forecast has no valid historical cutoff and price-capture time.');setLoading(false);return;}
      const params=new URLSearchParams({sport,player,before:cutoff,exact:'1',limit:'20'});
      fetch(`/api/gamelogs?${params}`,{cache:'no-store',signal:controller.signal})
        .then(async response=>{
          if(!response.ok) throw new Error('Recorded player history is temporarily unavailable.');
          return response.json();
        }).then(data=>{if(!controller.signal.aborted) setLogs(data.logs);})
        .catch(()=>{if(!controller.signal.aborted) setError('Recorded player history is temporarily unavailable.');})
        .finally(()=>{if(!controller.signal.aborted) setLoading(false);});
    },0);
    return ()=>{window.clearTimeout(timer);controller.abort();};
  },[sport,player,cutoff]);
  let history:ReturnType<typeof forecastHistory>|undefined;
  let invalid='';
  if(!loading && !error) {
    try {history=forecastHistory(logs,signal,count);} catch {invalid='Recorded history could not be validated for this forecast.';}
  }
  return <section className={styles.playerHistory} aria-label="Player history before forecast">
    <div className={styles.historyHeader}><div><h3>History behind the line</h3><p>Recorded games before {cutoff ?? 'an unavailable cutoff'}, compared with {signal.direction} {signal.line} {signal.prop_type.replaceAll('_',' ')}. A conservative one-day gap before price capture excludes overnight games.</p></div>
      <div className={styles.viewSwitch} aria-label="History window">{[10,20].map(n=><button type="button" key={n} aria-pressed={count===n} onClick={()=>setCount(n)}>Last {n}</button>)}</div>
    </div>
    {loading ? <p role="status">Loading recorded history…</p> : error || invalid ? <p role="status">{error || invalid}</p>
      : !history?.rows.length ? <p>No exact-player games are available before this forecast cutoff.</p> : <>
        <div className={styles.evidenceMetrics}>
          <div><span>Shown-game direction rate</span><strong>{history.rate===null ? 'Unavailable' : `${(history.rate*100).toFixed(0)}%`}</strong><small>{history.wins} of {history.decided} decided games</small></div>
          <div><span>Shown-game average</span><strong>{history.mean?.toFixed(1) ?? 'Unavailable'}</strong><small>Compared with line {signal.line}</small></div>
          <div><span>Recorded games shown</span><strong>{history.rows.length}</strong><small>{history.ties} ties · {history.missing} missing stats</small></div>
        </div>
        <div className={styles.historyOutcomes} aria-hidden="true">{[...history.rows].reverse().map(row=><span key={`${row.date}:${row.team}:${row.opponent}`} data-outcome={row.outcome} title={`${row.date}: ${row.stat ?? 'missing'} · ${row.outcome}`} />)}</div>
        <p className={styles.historyDisclaimer}>Descriptive history, not betting returns or a new probability. Ties and missing stats are excluded from the direction rate. This limited recent-game window does not reproduce the model’s full historical sample; no historical bookmaker prices are assumed.</p>
        <div className={styles.historyTable} tabIndex={0} aria-label="Pre-forecast game results"><table className="data-table"><caption>Recorded results at this forecast’s line</caption><thead><tr><th>Date</th><th>Matchup</th><th>Stat</th><th>At this line</th></tr></thead><tbody>{history.rows.map(row=><tr key={`${row.date}:${row.team}:${row.opponent}`}><td>{row.date}</td><td>{row.team} vs {row.opponent}</td><td>{row.stat ?? 'Unavailable'}</td><td>{row.outcome}</td></tr>)}</tbody></table></div>
      </>}
  </section>;
}
