'use client';
import { useState, useEffect } from 'react';
import type { Sport, PropType, EVSignal } from '@/lib/types';
import styles from './ResearchViews.module.css';
import PredictionEvidence,{REASONS} from './PredictionEvidence';
import {forecastWindow,publicSignals} from '@/lib/signalMetrics';
import PlayerPortrait from './PlayerPortrait';
import {Bookmark,RefreshCw,LayoutGrid,List} from 'lucide-react';
import {motion,useReducedMotion} from 'motion/react';

// PropAnalysis is derived from real EV signals — no mock data
interface PropsAnalysisProps { sport: Sport; }

const PROP_TYPES: PropType[] = ['points', 'rebounds', 'assists', 'threes', 'pra', 'steals', 'blocks', 'pass_yds', 'pass_tds', 'rush_yds', 'rec_yds', 'receptions'];
const PROP_LABELS:Record<PropType,string>={points:'Points',rebounds:'Rebounds',assists:'Assists',threes:'Three-pointers',pra:'Points + rebounds + assists',steals:'Steals',blocks:'Blocks',pass_yds:'Passing yards',pass_tds:'Passing touchdowns',rush_yds:'Rushing yards',rec_yds:'Receiving yards',receptions:'Receptions'};

function ProbabilityComparison({ model, implied, gated }: { model: number; implied: number; gated?: boolean }) {
  const edge = model - implied;
  return (
    <div style={{ minWidth: 160 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ fontSize: 12, color: 'var(--accent-cyan)' }}>MODEL {(model * 100).toFixed(0)}%</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>BOOK {(implied * 100).toFixed(0)}%</span>
      </div>
      <div style={{ position: 'relative', height: 6, background: 'var(--border-dim)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          position: 'absolute', left: 0, top: 0, bottom: 0,
          width: `${implied * 100}%`,
          background: 'var(--border-bright)',
        }} />
        <div style={{
          position: 'absolute', left: 0, top: 0, bottom: 0,
          width: `${model * 100}%`,
          background: gated ? 'var(--text-secondary)' : edge > 0 ? 'var(--accent-mint)' : 'var(--accent-red)',
          opacity: 0.7,
        }} />
      </div>
      <div style={{ textAlign: 'right', marginTop: 2 }}>
        <span style={{
          fontSize: 12, fontWeight: 600,
          color: gated ? 'var(--text-secondary)' : edge > 0 ? 'var(--accent-mint)' : 'var(--accent-red)',
        }}>
          {edge > 0 ? '+' : ''}{(edge * 100).toFixed(1)}pp edge
        </span>
      </div>
    </div>
  );
}

function ConfidenceBar({ ci, mean, line }: { ci: [number, number] | null; mean: number | null; line: number }) {
  return (
    <div style={{ minWidth: 130 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 3 }}>
        {ci ? `95% CI: [${(ci[0] * 100).toFixed(0)}%, ${(ci[1] * 100).toFixed(0)}%]` : "Uncertainty unavailable"}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        μ = <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{mean?.toFixed(1) ?? "Unavailable"}</span>
        {' '}/ line {line}
      </div>
    </div>
  );
}

export default function PropsAnalysis({ sport }: PropsAnalysisProps) {
  const [playerFilter, setPlayerFilter] = useState('');
  const [propFilter, setPropFilter] = useState<string>('all');
  const [minEV, setMinEV] = useState(0);
  const [allProps, setAllProps] = useState<EVSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [windowFilter,setWindowFilter]=useState('upcoming');
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [now,setNow]=useState(0);
  const [view,setView]=useState('cards');
  const [shortlist,setShortlist]=useState<string[]>([]);
  const [scope,setScope]=useState('all');
  const [sort,setSort]=useState('edge');
  const [refresh,setRefresh]=useState(0);
  const [storageNotice,setStorageNotice]=useState('');
  const reduceMotion=useReducedMotion();
  useEffect(()=>{
    const timer=window.setTimeout(()=>{
      try {
        const saved=JSON.parse(localStorage.getItem('forecast-players') ?? '[]');
        if(Array.isArray(saved)) setShortlist(saved.filter((value):value is string=>typeof value==='string' && value.length<=110).slice(0,500));
      } catch {setStorageNotice('Saved players are unavailable in this browser.');}
    },0);
    return ()=>window.clearTimeout(timer);
  },[]);
  function savePlayer(p:EVSignal) {
    const key=`${p.sport}:${p.player}`;
    const updated=shortlist.includes(key) ? shortlist.filter(item=>item!==key) : [...shortlist,key].slice(-500);
    setShortlist(updated);
    try {localStorage.setItem('forecast-players',JSON.stringify(updated));setStorageNotice('');}
    catch {setStorageNotice('Saved for this session. Browser storage is unavailable.');}
  }
  function resetFilters() {setPlayerFilter('');setPropFilter('all');setMinEV(0);setWindowFilter('upcoming');setScope('all');}

  useEffect(()=>{
    const timer=window.setInterval(()=>setNow(Date.now()),30_000);
    const initial=window.setTimeout(()=>setNow(Date.now()),0);
    return ()=>{window.clearInterval(timer);window.clearTimeout(initial);};
  },[]);

  useEffect(() => {
    const controller = new AbortController();
    let busy=false;
    const load=async () => {
      if(busy || document.visibilityState==='hidden') return;
      busy=true;
      setLoading(true);
      try {
        const response=await fetch(`/api/signals?sport=${sport}`, {cache:'no-store',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(15_000)])});
        const body=await response.json();
        if(!response.ok) throw new Error('Recorded forecasts could not be refreshed.');
        if(!Array.isArray(body.signals)) throw new Error('Invalid forecast response.');
        if(!controller.signal.aborted) {
          setAllProps(body.signals);
          setError('');
        }
      } catch {
        if(!controller.signal.aborted) setError('Refresh unavailable. Previously loaded forecasts remain visible; quote freshness still applies.');
      } finally {
        busy=false;
        if(!controller.signal.aborted) setLoading(false);
      }
    };
    const initial=window.setTimeout(load,0);
    const poll=window.setInterval(load,30_000);
    document.addEventListener('visibilitychange',load);
    return () => {window.clearTimeout(initial);window.clearInterval(poll);document.removeEventListener('visibilitychange',load);controller.abort();};
  }, [sport,refresh]);

  const leagueProps=PROP_TYPES.filter(p=>sport==='nfl' ? ['pass_yds','pass_tds','rush_yds','rec_yds','receptions'].includes(p) : !['pass_yds','pass_tds','rush_yds','rec_yds','receptions'].includes(p));
  const effectivePropFilter=leagueProps.includes(propFilter as PropType) ? propFilter : 'all';
  const currentProps=publicSignals(allProps,now).signals;
  const selected=currentProps.find(p=>p.id===selectedId && p.sport===sport);
  const props = currentProps.filter(p => {
    if (p.sport !== sport) return false;
    if(scope==='saved' && !shortlist.includes(`${p.sport}:${p.player}`)) return false;
    if(scope==='eligible' && p.gated) return false;
    if(windowFilter!=='all' && forecastWindow(p,now)!==windowFilter) return false;
    if (playerFilter && !p.player.toLowerCase().includes(playerFilter.toLowerCase())) return false;
    if (effectivePropFilter !== 'all' && p.prop_type !== effectivePropFilter) return false;
    if (minEV>0 && p.ev_pct < minEV / 100) return false;
    return true;
  }).sort((a,b)=>sort==='player' ? a.player.localeCompare(b.player) : sort==='sample' ? (b.sample_size ?? 0)-(a.sample_size ?? 0) : b.ev_pct-a.ev_pct);

  if (loading && !allProps.length) return (
    <div className={styles.loadingState}>
      <div className={styles.loadingPanel}>
        <span className="live-dot" style={{ width: 8, height: 8 }} />
        <span>Loading recorded prop estimates…</span>
      </div>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className={styles.forecastHeading}>
        <div><h2>Player forecasts</h2><p>Find a player. Check the evidence. Follow the next game.</p></div>
        <button className={styles.uxButton} type="button" onClick={()=>setRefresh(n=>n+1)} disabled={loading} aria-label="Refresh forecasts"><RefreshCw size={16} />{loading?'Refreshing...':'Refresh'}</button>
      </div>
      <div className={styles.forecastControls}>
        <input aria-label="Search player" className="term-input" placeholder="Search players..." value={playerFilter} onChange={e=>setPlayerFilter(e.target.value)} />
        <button className={styles.uxButton} type="button" aria-pressed={scope==='saved'} onClick={()=>setScope(scope==='saved'?'all':'saved')}><Bookmark size={16} />Saved players</button>
        <details className={styles.forecastFilters}>
          <summary>Filters{effectivePropFilter!=='all' || minEV>0 || windowFilter!=='upcoming' || scope==='eligible' ? ' - Active' : ''}</summary>
          <div className={styles.filterFields}>
            <label>Games<select aria-label="Forecast window" className="term-select" value={windowFilter} onChange={e=>setWindowFilter(e.target.value)}><option value="upcoming">Upcoming games</option><option value="archive">Past games</option><option value="all">All recorded forecasts</option></select></label>
            <label>Prop<select aria-label="Prop type" className="term-select" value={effectivePropFilter} onChange={e=>setPropFilter(e.target.value)}><option value="all">All props</option>{leagueProps.map(p=><option key={p} value={p}>{PROP_LABELS[p]}</option>)}</select></label>
            <label>Eligibility<select aria-label="Forecast shortlist" className="term-select" value={scope} onChange={e=>setScope(e.target.value)}><option value="all">All estimates</option><option value="saved">Saved players</option><option value="eligible">Research eligible</option></select></label>
            <label>Sort<select aria-label="Sort forecasts" className="term-select" value={sort} onChange={e=>setSort(e.target.value)}><option value="edge">Highest edge</option><option value="sample">Largest sample</option><option value="player">Player A-Z</option></select></label>
            <label htmlFor="prop-min-edge">Minimum edge: {minEV}pp<input id="prop-min-edge" aria-valuetext={`${minEV} percentage points`} type="range" min={0} max={20} step={1} value={minEV} onChange={e=>setMinEV(Number(e.target.value))} /></label>
            <button className={styles.uxButton} type="button" onClick={resetFilters}>Reset filters</button>
          </div>
        </details>
        <div className={styles.viewSwitch} aria-label="Forecast view"><button type="button" aria-pressed={view==='cards'} onClick={()=>setView('cards')}><LayoutGrid size={16} />Cards</button><button type="button" aria-pressed={view==='table'} onClick={()=>setView('table')}><List size={16} />Table</button></div>
      </div>
      <div className={styles.forecastSummary} role="status"><span>{props.length} forecasts | {new Set(props.map(p=>p.player)).size} players</span><span>{props.filter(p=>!p.gated).length} research eligible</span></div>
      {storageNotice && <p role="status" className={styles.forecastIntro}>{storageNotice}</p>}

      {error && <div className={styles.notice} role="alert">{error}</div>}
      <p className={styles.forecastIntro}>Prices are recorded observations, not live quotes. Quotes expire after five minutes. Saved players stay in this browser.</p>
      {selected && <PredictionEvidence signal={selected} onClose={()=>{setSelectedId(null);document.getElementById(`forecast-${selected.id}`)?.focus();}} />}

      {/* Table */}
      <div style={{ flex: 1, overflow: 'auto' }} tabIndex={0} aria-label="Recorded player prop estimates">
        {props.length === 0 ? (
          <div className={styles.propsEmpty}>
            <strong>{scope==='saved' ? 'Your saved-player view is empty.' : allProps.length ? 'No forecasts match these filters.' : `No recorded ${sport.toUpperCase()} forecasts are published yet.`}</strong>
            <span>{scope==='saved' ? 'Use the bookmark next to a player to save them. Other filters still apply to your saved players.' : allProps.length ? 'Try all recorded forecasts, another player, or a lower minimum edge.' : 'The scheduled scan covers the next 48 hours, subject to source availability and the API budget. Forecasts require real pregame prices and sufficient player history.'}</span>
            {allProps.length>0 && <button className={styles.uxButton} type="button" onClick={()=>{resetFilters();setWindowFilter('all');}}>Show all forecasts</button>}
          </div>
        ) : view==='cards' ? <div className={styles.forecastGrid}>{props.map(p=><motion.article key={p.id} className={styles.forecastCard} initial={reduceMotion ? false : {opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:.2}}>
          <div className={styles.playerHeading}><PlayerPortrait signal={p} /><div><button id={`forecast-${p.id}`} type="button" className={styles.forecastPlayer} onClick={()=>setSelectedId(p.id)}>{p.player}<span>Explore forecast →</span></button><small>{p.availability?.team ?? p.sport.toUpperCase()} · {new Date(p.game_start_time ?? '').toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</small></div><SaveButton prop={p} saved={shortlist.includes(`${p.sport}:${p.player}`)} onSave={()=>savePlayer(p)} /></div>
          <h3>{p.direction} {p.line} <span>{PROP_LABELS[p.prop_type]}</span></h3>
          <p className={styles.cardMatchup}>{p.home_team} vs {p.away_team} | <QuoteAge signal={p} now={now} /></p>
          <ProbabilityComparison model={p.true_prob} implied={p.implied_prob} gated={p.gated} />
          <div className={styles.cardFooter}><span className={`badge ${p.gated ? 'badge-dim' : 'badge-mint'}`}>{p.gated ? 'Blocked estimate' : 'Research eligible'}</span><span>{p.sample_size} games · {p.sportsbook}</span></div>
          {p.gated && <p className={styles.cardGate}>{REASONS[p.gate_reason ?? ''] ?? 'A model or portfolio risk gate blocked this pick.'}</p>}
        </motion.article>)}</div> : <table className="data-table">
          <thead>
            <tr>
              <th>Player</th>
              <th>Prop</th>
              <th>Line / Dir</th>
              <th>Probability Comparison</th>
              <th>Edge (pp)</th>
              <th>Kelly</th>
              <th>Stats</th>
              <th>Book / Odds</th>
            </tr>
          </thead>
          <tbody>
            {props.map(p => <PropRow key={p.id} prop={p} onExplain={()=>setSelectedId(p.id)} saved={shortlist.includes(`${p.sport}:${p.player}`)} onSave={()=>savePlayer(p)} now={now} />)}
          </tbody>
        </table>}
      </div>
    </div>
  );
}

function SaveButton({prop,saved,onSave}:{prop:EVSignal;saved:boolean;onSave:()=>void}) {
  return <button type="button" className={styles.savePlayer} aria-label={`${saved?'Unsave':'Save'} ${prop.player}`} aria-pressed={saved} onClick={onSave}><Bookmark size={18} fill={saved?'currentColor':'none'} /></button>;
}

function PropRow({ prop,onExplain,saved,onSave,now }: { prop: EVSignal;onExplain:()=>void;saved:boolean;onSave:()=>void;now:number }) {
  const evPct = prop.ev_pct * 100;
  return (
    <tr>
      <td>
        <div className={styles.playerHeading}><PlayerPortrait signal={prop} /><SaveButton prop={prop} saved={saved} onSave={onSave} /></div>
        <button id={`forecast-${prop.id}`} type="button" className={styles.forecastPlayer} onClick={onExplain}>{prop.player}<span>Why this forecast →</span></button>
        <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>{prop.team || prop.home_team} vs {prop.opponent || prop.away_team}</div>
        <span className={`badge ${prop.gated ? 'badge-dim' : 'badge-mint'}`}>{prop.gated ? 'Blocked estimate' : 'Research eligible'}</span>
      </td>
      <td>
        <span className={`badge ${prop.sport === 'nba' ? 'badge-blue' : 'badge-purple'}`} style={{ marginBottom: 3, display: 'block', width: 'fit-content' }}>
          {prop.sport.toUpperCase()}
        </span>
        <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
          {prop.prop_type.replace('_', ' ').toUpperCase()}
        </span>
      </td>
      <td>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 13 }}>{prop.line}</div>
        <span className={`badge ${prop.direction === 'over' ? 'badge-mint' : 'badge-red'}`}>
          {prop.direction.toUpperCase()}
        </span>
      </td>
      <td>
        <ProbabilityComparison model={prop.true_prob} implied={prop.implied_prob} gated={prop.gated} />
      </td>
      <td>
        <span style={{
          color: prop.gated ? 'var(--text-secondary)' : evPct >= 10 ? 'var(--accent-mint)' : evPct >= 5 ? 'var(--accent-amber)' : 'var(--text-secondary)',
          fontWeight: 700, fontSize: 13,
        }}>{evPct>0?'+':''}{evPct.toFixed(1)}pp</span>
      </td>
      <td>
        <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>
          {(prop.kelly_fraction * 100).toFixed(1)}%
        </span>
        <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>of bankroll</div>
      </td>
      <td>
        <ConfidenceBar ci={prop.confidence_interval ?? null} mean={prop.mean_stat ?? null} line={prop.line} />
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>n={prop.sample_size}</div>
      </td>
      <td>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span className="badge badge-dim">{prop.sportsbook}</span><QuoteAge signal={prop} now={now} />
          <span style={{ color: 'var(--text-secondary)', fontSize: 11, fontWeight: 600 }}>
            {prop.american_odds > 0 ? '+' : ''}{prop.american_odds}
          </span>
        </div>
      </td>
    </tr>
  );
}

function QuoteAge({signal,now}:{signal:EVSignal;now:number}) {
  const age=now-Date.parse(signal.snapped_at ?? '');
  if(!Number.isFinite(age) || age<0 || !now) return <span>Quote age unavailable</span>;
  const minutes=Math.floor(age/60000);
  const text=minutes<1?'just now':minutes<60?`${minutes}m ago`:minutes<1440?`${Math.floor(minutes/60)}h ago`:`${Math.floor(minutes/1440)}d ago`;
  return <span>Quote {text}{age>300000?' - expired':''}</span>;
}
