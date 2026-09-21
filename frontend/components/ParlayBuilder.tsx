'use client';

import {useEffect,useMemo,useState} from 'react';
import {AlertTriangle,Check,Plus,RefreshCw,Sparkles,X} from 'lucide-react';
import type {PickBoard,PickBoardRecord} from '@/lib/pickBoard';
import {PROP_LABELS} from '@/lib/pickTerms';
import {assistantReasons,assistedSlip,dependenceEnvelope,expectedSlipReturn,MAX_SLIP_LEGS,slipWarnings,type SlipMode} from '@/lib/slipBuilder';
import type {Sport} from '@/lib/types';
import PlayerPortrait from './PlayerPortrait';
import styles from './ResearchViews.module.css';

const pct=(value:number)=>`${(value*100).toFixed(1)}%`;
const EMPTY_RECORDS:PickBoardRecord[]=[];
const modes:Array<{id:SlipMode;label:string;copy:string}>=[
  {id:'balanced',label:'Balanced',copy:'Best confidence floors, separate games first'},
  {id:'conservative',label:'Conservative',copy:'Up to two highest individual probabilities'},
  {id:'diversified',label:'Diversified',copy:'Maximize distinct games before adding a second'},
];

export default function ParlayBuilder({sport}:{sport:Sport}) {
  const [board,setBoard]=useState<PickBoard|null>(null),[selected,setSelected]=useState<string[]>([]);
  const [mode,setMode]=useState<SlipMode>('balanced'),[payout,setPayout]=useState(''),[error,setError]=useState('');
  const [edited,setEdited]=useState(false);
  const [loading,setLoading]=useState(true),[revision,setRevision]=useState(0);

  useEffect(()=>{
    const controller=new AbortController();
    const signal=AbortSignal.any([controller.signal,AbortSignal.timeout(15_000)]);
    fetch(`/api/picks?sport=${sport}`,{cache:'no-store',signal}).then(async response=>{
      if(!response.ok) throw new Error('Pick board unavailable');
      const value=await response.json() as PickBoard;
      if(!Array.isArray(value.current)) throw new Error('Pick board unavailable');
      setBoard(value);
      setMode('balanced');
      setEdited(false);
      setSelected(assistedSlip(value.current,'balanced').map(record=>record.id));
    }).catch(()=>{if(!controller.signal.aborted){setBoard(null);setError('The approved pick board could not be loaded.');}})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[sport,revision]);

  const candidates=board?.current ?? EMPTY_RECORDS;
  const legs=useMemo(()=>candidates.filter(record=>selected.includes(record.id)),[candidates,selected]);
  const envelope=dependenceEnvelope(legs),returns=expectedSlipReturn(envelope,Number(payout));
  const warnings=slipWarnings(legs),reasons=assistantReasons(legs,mode,edited);
  const rebuild=(next:SlipMode)=>{setMode(next);setEdited(false);setSelected(assistedSlip(candidates,next).map(record=>record.id));};
  const toggle=(record:PickBoardRecord)=>{setEdited(true);setSelected(ids=>ids.includes(record.id)
    ? ids.filter(id=>id!==record.id)
    : ids.length<MAX_SLIP_LEGS ? [...ids,record.id] : ids);};

  return <section className={styles.toolView} aria-labelledby="slip-title">
    <header className={styles.toolHeader}><div><small>Evidence-grounded assistant</small><h2 id="slip-title">Slip builder</h2></div><p>Build from worker-approved pregame picks only. The assistant ranks existing evidence, checks shared exposure, and explains uncertainty. It cannot create picks or place orders.</p></header>

    <section className={styles.assistantBar} aria-label="Slip assistant">
      <div className={styles.assistantIdentity}><Sparkles aria-hidden="true" /><div><strong>AI slip assistant</strong><span>Deterministic · no generated legs</span></div></div>
      <div className={styles.modePicker}>{modes.map(item=><button type="button" key={item.id} aria-pressed={mode===item.id} title={item.copy} onClick={()=>rebuild(item.id)}>{item.label}</button>)}</div>
      <button type="button" className={styles.rebuildButton} disabled={!candidates.length} onClick={()=>rebuild(mode)}><RefreshCw size={15} />Build best slip</button>
    </section>

    {loading ? <SlipSkeleton /> : error ? <div className={styles.slipError} role="alert"><strong>Slip unavailable</strong><span>{error}</span><button type="button" onClick={()=>{setLoading(true);setError('');setRevision(value=>value+1);}}>Try again</button></div> :
      <div className={styles.slipGrid}>
        <section className={styles.pickPool} aria-labelledby="suggested-picks-title">
          <div className={styles.slipSectionHeading}><div><span>Approved board</span><h3 id="suggested-picks-title">Suggested picks</h3></div><strong>{candidates.length} available</strong></div>
          {!candidates.length ? <div className={styles.slipEmpty}><strong>No approved pregame picks</strong><p>The assistant will not fill an empty board with research forecasts. Check again after the next worker scan.</p></div> :
            <div className={styles.slipCandidates}>{candidates.map(record=>{
              const active=selected.includes(record.id),profile=record.player_profile;
              return <article className={active?styles.slipCandidateActive:styles.slipCandidate} key={record.id}>
                <header><PlayerPortrait signal={record} /><div><strong>{record.player}</strong><small>{profile?.team ?? record.team}{profile?.jersey?` · #${profile.jersey}`:''}{profile?.position?` · ${profile.position}`:''}</small></div><span>{record.board_state==='locked'?'Locked T-60':'Recorded · reprice'}</span></header>
                <h4>{record.direction==='over'?'Over':'Under'} {record.line} {PROP_LABELS[record.prop_type]}</h4>
                <p>{record.away_team} at {record.home_team} · {new Date(record.game_start_time ?? '').toLocaleString(undefined,{weekday:'short',hour:'numeric',minute:'2-digit'})}</p>
                <dl><div><dt>Model</dt><dd>{pct(record.true_prob)}</dd></div><div><dt>Confidence floor</dt><dd>{record.confidence_interval?pct(record.confidence_interval[0]):'Unavailable'}</dd></div><div><dt>Recorded price</dt><dd>{record.sportsbook} {record.american_odds>0?'+':''}{record.american_odds}</dd></div></dl>
                <button type="button" aria-label={`${active?'Remove':'Add'} ${record.player} ${record.direction} ${record.line} ${PROP_LABELS[record.prop_type]}`} aria-pressed={active} onClick={()=>toggle(record)}>{active?<><Check size={15}/>In slip</>:<><Plus size={15}/>Add pick</>}</button>
              </article>;
            })}</div>}
        </section>

        <aside className={styles.slipPanel} aria-labelledby="your-slip-title">
          <div className={styles.slipSectionHeading}><div><span>Read-only plan</span><h3 id="your-slip-title">Your slip</h3></div><strong>{legs.length}/{MAX_SLIP_LEGS} legs</strong></div>
          {!legs.length ? <div className={styles.slipEmpty}><strong>Choose a suggested pick</strong><p>Use the assistant or add a board-approved leg. Nothing here is sent to a sportsbook.</p></div> : <>
            <ol className={styles.selectedLegs}>{legs.map((record,index)=><li key={record.id}><span>{index+1}</span><div><strong>{record.player}</strong><small>{record.direction==='over'?'Over':'Under'} {record.line} {PROP_LABELS[record.prop_type]} · {pct(record.true_prob)}</small></div><button type="button" aria-label={`Remove ${record.player}`} onClick={()=>toggle(record)}><X size={15}/></button></li>)}</ol>
            <section className={styles.assistantReason}><header><Sparkles size={16}/><strong>{edited?'Edited slip':'Why this build'}</strong></header>{reasons.map(reason=><p key={reason}>{reason}</p>)}</section>
            {warnings.length>0&&<section className={styles.slipWarnings}><header><AlertTriangle size={16}/><strong>Checks before use</strong></header><ul>{warnings.map(warning=><li key={warning}>{warning}</li>)}</ul></section>}
            {envelope&&<section className={styles.slipMath} aria-label="Slip probability scenarios"><div><span>Independence scenario</span><strong>{pct(envelope.independent)}</strong></div><div><span>Dependence range</span><strong>{pct(envelope.lower)}–{pct(envelope.upper)}</strong></div><p>The model has not estimated a joint probability. The range is the mathematically valid envelope from the individual estimates.</p><label htmlFor="slip-payout">Exact offered total return per $1<input id="slip-payout" type="number" min="1.01" max="100000" step="0.01" inputMode="decimal" value={payout} onChange={event=>setPayout(event.target.value)} placeholder="e.g. 3.20" /></label>{returns&&<div className={styles.returnRange}><span>Expected-return scenarios</span><strong>{pct(returns.lower)} to {pct(returns.upper)}</strong><small>Independence case {returns.independent>=0?'+':''}{pct(returns.independent)}. Recheck every line and the exact combined payout.</small></div>}</section>}
            <footer className={styles.slipFooter}>You control any financial decision. Linework provides research, cannot guarantee outcomes, and does not place bets.</footer>
          </>}
        </aside>
      </div>}
  </section>;
}

function SlipSkeleton(){return <div className={styles.slipSkeleton} role="status" aria-label="Loading approved picks"><section><i/><i/><i/></section><aside><i/><i/></aside></div>;}
