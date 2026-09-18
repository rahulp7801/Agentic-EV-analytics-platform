'use client';
import {useState} from 'react';
import Image from 'next/image';
import Link from 'next/link';
import {motion,useReducedMotion} from 'motion/react';
import {WEEK_ONE_DEMO,demoResult,DEFAULT_DEMO_INDEX} from '@/lib/weekOneDemo';
import styles from './HistoricalFlowDemo.module.css';

export default function HistoricalFlowDemo() {
  const [player,setPlayer]=useState(DEFAULT_DEMO_INDEX);
  const reduce=useReducedMotion(),record=WEEK_ONE_DEMO[player],result=demoResult(record);
  return <section id="demo" className={styles.demo} aria-label="Week 1 historical walkthrough">
    <header><div><span className={styles.badge}>PAST-GAME DEMO · NFL WEEK 1</span><h3>The forecast. The final result.</h3></div>
      <label>Compare a replay<select aria-label="Demo player" value={player} onChange={event=>setPlayer(Number(event.target.value))}>
        {WEEK_ONE_DEMO.map((item,index)=><option key={item.player} value={index}>{item.player} · {demoResult(item).correct ? 'Correct' : 'Missed'}</option>)}
      </select></label></header>
    <motion.div key={record.player} initial={reduce ? false : {opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:.2}} aria-live="polite">
      <div className={styles.pickGrid}>
        <div className={styles.pick}><div className={styles.player}>
          <Image src={`https://a.espncdn.com/i/headshots/nfl/players/full/${record.athlete}.png`} alt="" width={80} height={80} unoptimized referrerPolicy="no-referrer" />
          <div><small>{record.team} vs {record.opponent} · {record.date}</small><h4>{record.player}</h4></div>
        </div><span className={styles.eyebrow}>RETROSPECTIVE MODEL FORECAST</span><h4 className={styles.pickTitle}>Over {record.threshold}<span>passing yards</span></h4>
          <p>A fixed research threshold, evaluated against the final game stat.</p></div>
        <div className={`${styles.result} ${result.correct ? '' : styles.resultMissed}`}><span>Verified final passing yards</span><strong>{record.actual}<small> yd</small></strong>
          <b className={result.correct ? styles.correct : styles.missed}>{result.correct ? '✓ Correct forecast' : 'Missed forecast'}</b>
          <p>{result.outcome}</p>
          <a href={`https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=${record.event}`} target="_blank" rel="noreferrer">View final-stat source ↗</a>
        </div>
      </div>
      <div className={styles.metrics}><div><span>Model baseline</span><strong>{(record.probability*100).toFixed(1)}%</strong><small>Above the research threshold</small></div>
        <div><span>History behind it</span><strong>{record.sample} games</strong><small>Before the target game date</small></div>
        <div><span>Evidence</span><strong>Final stat verified</strong><small>Exact player and game match</small></div></div>
      <details className={styles.explanation}><summary>Why this forecast? Inspect the evidence</summary>
        <p>The retained retrospective model replay estimated {(record.probability*100).toFixed(1)}% probability above {record.threshold} passing yards using {record.sample} prior games. It used an exclusive game-date cutoff and up to 40 prior games; the final stat for the target game was used only for grading.</p>
        <p>This is a historical model demonstration, not a recorded pregame recommendation. The threshold is a research choice. Historical sportsbook prices, a retained uncertainty interval and timestamped injury evidence are absent from this replay, so it cannot establish betting value, stake, ROI or CLV. No injury probability boost is implied.</p>
        <p>Demo records remain separate from the live shortlist and performance totals.</p><small>Retained final-stat source commitment</small><code>{record.source_sha256}</code>
      </details>
    </motion.div>
    <footer><span>Retrospective research replay · September 10–13, 2026</span><Link href="/terminal#nfl/props">Explore current forecasts →</Link></footer>
  </section>;
}
