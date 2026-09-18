'use client';
import {useState} from 'react';
import Image from 'next/image';
import {motion,useReducedMotion} from 'motion/react';
import {WEEK_ONE_DEMO,demoResult} from '@/lib/weekOneDemo';
import styles from './HistoricalFlowDemo.module.css';
const STEPS=['Game','Model','Quality check','Result'];
export default function HistoricalFlowDemo() {
  const [player,setPlayer]=useState(0),[step,setStep]=useState(0);
  const reduce=useReducedMotion(),record=WEEK_ONE_DEMO[player],result=demoResult(record);
  return <section className={styles.demo} aria-label="Week 1 historical walkthrough">
    <header><div><span className={styles.badge}>NFL WEEK 1 · FIXED RETROSPECTIVE DEMO</span><h3>A forecast, from start to finish.</h3><p>September 10–13, 2026. Actual final stats and retained model replays. These were not recorded pregame recommendations.</p></div>
      <label>Explore a player<select aria-label="Demo player" value={player} onChange={event=>{setPlayer(Number(event.target.value));setStep(0);}}>{WEEK_ONE_DEMO.map((record,index)=><option key={record.player} value={index}>{record.player}</option>)}</select></label></header>
    <nav aria-label="Demo stages">{STEPS.map((label,index)=><button type="button" key={label} aria-pressed={step===index} onClick={()=>setStep(index)}><span>{index+1}</span>{label}</button>)}</nav>
    <motion.div key={record.player+step} initial={reduce ? false : {opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:.2}} className={styles.stage} aria-live="polite">
      <div className={styles.player}><Image src={`https://a.espncdn.com/i/headshots/nfl/players/full/${record.athlete}.png`} alt="" width={80} height={80} unoptimized referrerPolicy="no-referrer" /><div><small>{record.team} vs {record.opponent} · {record.date}</small><h4>{record.player}</h4><p>Passing yards · Research threshold {record.threshold}</p></div></div>
      {step===0 && <><h4>Start with the exact game.</h4><p>Match the player, opponent and event before looking at the model. This fixed threshold was used for research; it is not an archived sportsbook offer.</p><div className={styles.metrics}><div><span>Research threshold</span><strong>{record.threshold} yd</strong></div><div><span>Historical price</span><strong>Unavailable</strong></div></div></>}
      {step===1 && <><h4>Use history from before kickoff.</h4><p>The retained retrospective replay used an exclusive game-date cutoff and up to 40 prior games. Final Week 1 stats were used only for grading.</p><div className={styles.metrics}><div><span>Above-threshold baseline</span><strong>{(record.probability*100).toFixed(1)}%</strong></div><div><span>Prior-game sample</span><strong>{record.sample} games</strong></div></div><p>This point estimate is not a validated injury adjustment or sufficient evidence for a bet.</p></>}
      {step===2 && <><h4>A promising baseline still needs proof.</h4><p>Historical bookmaker price, a retained uncertainty interval and timestamped pregame injury evidence are not available in this demo. Break-even, conservative edge and stake cannot be established.</p><div className={styles.decision}><strong>Research only · No pick issued</strong><span>The demo never enters the live shortlist or accepted-recommendation statistics.</span></div></>}
      {step===3 && <><h4>Keep the result, including the misses.</h4><div className={styles.metrics}><div><span>Observed final passing yards</span><strong>{record.actual} yd</strong></div><div><span>Baseline direction</span><strong>{result.correct ? 'Correct' : 'Missed'}</strong></div></div><p>{result.outcome}. This grades a fixed research threshold, not a sportsbook bet. ROI and CLV remain unavailable without historical prices.</p><a href={`https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=${record.event}`} target="_blank" rel="noreferrer">Inspect the final-stat source ↗</a><details><summary>Retained source commitment</summary><code>{record.source_sha256}</code></details></>}
    </motion.div>
    <footer><span>Read-only walkthrough · No orders or profit claim</span><button type="button" onClick={()=>setStep((step+1)%STEPS.length)}>{step===3 ? 'Replay flow' : `Next: ${STEPS[step+1]}`} →</button></footer>
  </section>;
}
