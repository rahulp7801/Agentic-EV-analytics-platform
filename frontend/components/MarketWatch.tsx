'use client';
import { useEffect, useState } from 'react';
import type { Sport } from '@/lib/types';

interface Observation {
  captured_at: string;
  scope: string;
  sources: Record<string,{status:string;count:number;partial_coverage:boolean}>;
  comparisons: {identity:string;kind:string;title:string;gross_cost:string;gross_gap_to_one_dollar:string;
    reasons:string[];legs:{book:string;team:string;cost:string;observed_at:string}[]}[];
}

export default function MarketWatch({sport}:{sport:Sport}) {
  const [data,setData] = useState<Observation|null>(null);
  const [error,setError] = useState('');
  const [now,setNow] = useState(Date.now());
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError('');
    async function load() {
      try {
        const response=await fetch('/api/markets?sport='+sport,{signal:controller.signal,cache:'no-store'});
        const body=await response.json();
        if (!response.ok) throw new Error(body.error || 'Market observations unavailable.');
        setData(body);setError('');setNow(Date.now());
      } catch (error) {
        if (!controller.signal.aborted) {setError(error instanceof Error ? error.message : 'Market observations unavailable.');setNow(Date.now());}
      }
    }
    void load();
    const timer=setInterval(()=>void load(),30000);
    return ()=>{controller.abort();clearInterval(timer);};
  },[sport]);
  const age=data ? (now-Date.parse(data.captured_at))/1000 : null;
  return <section style={{padding:16,height:'100%',overflow:'auto'}}>
    <h2>Market comparisons</h2>
    <p>Sportsbooks · Kalshi · PrizePicks — observation and research only</p>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p>Loading observations…</p>}
    {data && <>
      <p>{data.scope}</p>
      <p>Captured {new Date(data.captured_at).toLocaleString()} · {age!==null && Number.isFinite(age) && age>=0 && age<=30 ? 'Recent observation' : 'Stale observation — refresh required'}</p>
      <ul>{Object.entries(data.sources).map(([name,source])=><li key={name}>
        {name}: {source.status} · {source.count} source records{source.partial_coverage ? ' · partial coverage' : ''}
      </li>)}</ul>
      <p>Positive gross gaps are screening leads, not profit. PrizePicks requires a complete entry payout; projection lines alone cannot establish an arbitrage.</p>
      {data.comparisons.length===0 && <p>No comparisons could be built from this capture.</p>}
      {data.comparisons.map(row=><article className="card" key={row.kind+row.identity} style={{padding:12,marginBottom:10}}>
        <strong>{row.title}</strong> · {row.kind.replaceAll('_',' ')} · Unverified
        <p>Cost per $1 binary payoff: ${Number(row.gross_cost).toFixed(4)} · gross gap: ${Number(row.gross_gap_to_one_dollar).toFixed(4)}</p>
        <ul>{row.legs.map((leg,index)=><li key={index}>{leg.book}: {leg.team} · ${Number(leg.cost).toFixed(4)} · observed {new Date(leg.observed_at).toLocaleTimeString()}</li>)}</ul>
        <p>{row.reasons.join(' ')}</p>
      </article>)}
    </>}
  </section>;
}
