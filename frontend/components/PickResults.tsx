'use client';
import {useEffect,useMemo,useState} from 'react';
import {Check,Clock3,X} from 'lucide-react';
import type {PickBoard,PickBoardRecord} from '@/lib/pickBoard';
import type {Sport} from '@/lib/types';
import {PROP_LABELS,sportsbookLabel} from '@/lib/pickTerms';
import PlayerPortrait from './PlayerPortrait';
import styles from './PickResults.module.css';

export default function PickResults({sport}:{sport:Sport}) {
  const [board,setBoard]=useState<PickBoard|null>(null),[error,setError]=useState('');
  useEffect(()=>{const controller=new AbortController();
    fetch(`/api/picks?sport=${sport}`,{cache:'no-store',signal:controller.signal}).then(async response=>{
      if(!response.ok) throw new Error('Results unavailable');return response.json() as Promise<PickBoard>;
    }).then(setBoard).catch(reason=>{if(reason?.name!=='AbortError')setError('Verified pick results could not be loaded.');});
    return()=>controller.abort();},[sport]);
  const rows=useMemo(()=>[...(board?.history ?? [])].sort((a,b)=>b.true_prob-a.true_prob || Date.parse(b.game_start_time!)-Date.parse(a.game_start_time!)),[board]);
  return <section className={styles.results} aria-labelledby="results-title"><header><div><span>{sport.toUpperCase()} / AUDITED PICK LEDGER</span><h1 id="results-title">Past picks, with receipts.</h1><p>Only recommendations frozen by the prospective T−60 policy appear here. Results require reproducible final-stat evidence.</p></div><div className={styles.policy}><strong>60 min</strong><span>fixed pregame lock</span></div></header>
    {!board && !error && <ResultsSkeleton />}{error && <p className={styles.error} role="alert">{error}</p>}
    {board && <><div className={styles.metrics}><Metric label="Verified decisions" value={String(board.summary.wins+board.summary.losses)} /><Metric label="Wins" value={String(board.summary.wins)} /><Metric label="Losses" value={String(board.summary.losses)} /><Metric label="Verified win rate" value={board.summary.wins+board.summary.losses ? `${(board.summary.wins/(board.summary.wins+board.summary.losses)*100).toFixed(1)}%` : 'Awaiting results'} /></div>
      <section className={styles.ledger}><div className={styles.ledgerHead}><div><span>Highest model probability first</span><h2>Locked recommendation history</h2></div><small>{board.summary.settled} settled · {board.summary.pending} pending</small></div>
        {rows.length ? <div className={styles.table} role="table" aria-label="Past locked picks"><div className={styles.columns} role="row"><span>Player and pick</span><span>Recorded price</span><span>Model</span><span>Actual</span><span>Result</span></div>{rows.map(row=><ResultRow key={row.id} row={row} />)}</div> : <div className={styles.empty}><Clock3 /><h3>No locked picks have reached kickoff.</h3><p>The ledger starts prospectively. A pick appears after the worker approves it and the one-hour lock passes; the result stays pending until final stats reproduce the grade.</p></div>}
      </section><p className={styles.note}>Pushes and voids do not count as wins or losses. Displayed sportsbook prices are the immutable recorded prices, not current offers. No orders are placed.</p></>}
  </section>;
}

function Metric({label,value}:{label:string;value:string}) {return <article><span>{label}</span><strong>{value}</strong></article>;}
function ResultRow({row}:{row:PickBoardRecord}) {
  const pick=`${row.direction==='over'?'Over':'Under'} ${row.line} ${PROP_LABELS[row.prop_type]}`;
  const status=row.result==='win' ? <><Check />Win</> : row.result==='loss' ? <><X />Loss</> : <><Clock3 />{row.result==='pending'?'Pending':row.result}</>;
  return <article className={styles.row} role="row"><div className={styles.player}><PlayerPortrait signal={row} /><div><strong>{row.player}</strong><span>{pick}</span><small>{row.home_team} vs {row.away_team} · {new Date(row.game_start_time!).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'})}</small></div></div><div><strong>{sportsbookLabel(row.sportsbook)}</strong><span>{row.american_odds>0?'+':''}{row.american_odds}</span></div><div><strong>{(row.true_prob*100).toFixed(1)}%</strong><span>{(row.implied_prob*100).toFixed(1)}% break-even</span></div><div><strong>{row.result_verified ? row.actual_value : '—'}</strong><span>{row.result_verified ? PROP_LABELS[row.prop_type] : 'Final stats pending'}</span></div><div className={`${styles.status} ${row.result==='win'?styles.win:row.result==='loss'?styles.loss:styles.pending}`}>{status}</div></article>;
}
function ResultsSkeleton(){return <div className={styles.skeleton} role="status" aria-label="Loading verified pick history"><span/><span/><span/><span/></div>;}
