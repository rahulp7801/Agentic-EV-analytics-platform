'use client';
import { useEffect, useState } from 'react';

type Status = {label:string;updated_at:string|null;eligible:number|null;completed:number|null;deferred:number|null;
  selections:number|null;model_requests:number|null;model_estimates:number|null};
export default function ScanStatus() {
  const [data,setData]=useState<Record<string,Status>|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{
    const controller=new AbortController();
    async function load() {
      try {
        const response=await fetch('/api/scans',{cache:'no-store',signal:controller.signal});
        if (!response.ok) throw new Error('Daily scan status unavailable');
        setData(await response.json());setError('');
      } catch {if (!controller.signal.aborted) {setData(null);setError('Daily scan status unavailable');}}
    }
    void load();const timer=setInterval(()=>void load(),30000);
    return ()=>{controller.abort();clearInterval(timer);};
  },[]);
  return <div aria-live="polite" style={{padding:'6px 14px',fontSize:11,borderBottom:'1px solid var(--border-dim)',display:'flex',gap:20,flexWrap:'wrap'}}>
    {error || (!data ? 'Checking daily scans…' : Object.entries(data).map(([sport,status])=><span key={sport}>
      <strong>{sport.toUpperCase()} props:</strong> {status.label}
      {status.eligible!==null && status.completed!==null && ` · ${status.completed}/${status.eligible} games`}
      {status.selections!==null && status.selections>0 && ` · ${status.model_estimates}/${status.selections} modeled selections`}
      {status.updated_at && ` · ${new Date(status.updated_at).toLocaleTimeString()}`}
    </span>))}
  </div>;
}
