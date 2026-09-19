'use client';
import { useState, useEffect, useRef } from 'react';
import type { Sport, PropType, EVSignal } from '@/lib/types';
import styles from './ResearchViews.module.css';
import PredictionEvidence,{REASONS} from './PredictionEvidence';
import {forecastWindow,latestForecastWindow,publicSignals} from '@/lib/signalMetrics';
import PlayerPortrait from './PlayerPortrait';
import {Bookmark,RefreshCw,LayoutGrid,List} from 'lucide-react';
import {motion,useReducedMotion} from 'motion/react';
import {compareQuality,groupAlternateLines} from '@/lib/bestPicks';
import {fetchForecasts} from '@/lib/fetchForecasts';

// PropAnalysis is derived from real EV signals — no mock data
interface PropsAnalysisProps { sport: Sport; initialPlayer?:string; }

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

export default function PropsAnalysis({ sport,initialPlayer='' }: PropsAnalysisProps) {
  const [playerFilter, setPlayerFilter] = useState(initialPlayer);
  const [propFilter, setPropFilter] = useState<string>('all');
  const [minEV, setMinEV] = useState(0);
  const [library,setLibrary]=useState<Awaited<ReturnType<typeof fetchForecasts>>|null>(null);
  const allProps=library?.signals ?? [];
  const request=useRef<AbortController|null>(null),busy=useRef(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [windowFilter,setWindowFilter]=useState(initialPlayer ? 'all' : 'latest');
  const [visibleCount,setVisibleCount]=useState(24);
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [now,setNow]=useState(0);
  const [view,setView]=useState('cards');
  const [shortlist,setShortlist]=useState<string[]>([]);
  const [scope,setScope]=useState('all');
  const [sort,setSort]=useState('quality');
  const [refresh,setRefresh]=useState(0);
  const [storageNotice,setStorageNotice]=useState('');
  const coverageNotice=library && !library.complete ? `Showing ${allProps.length} of ${library.total_count} recent forecasts. Search and filters apply to this loaded research window; the qualified shortlist is checked independently.${library.cursor && library.cursor.offset>=1000 ? ' This view is capped at 1,000 archive rows.' : ''}` : '';
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
  function resetFilters() {setPlayerFilter('');setPropFilter('all');setMinEV(0);setWindowFilter('latest');setScope('all');setVisibleCount(24);}

  useEffect(()=>{
    const timer=window.setInterval(()=>setNow(Date.now()),30_000);
    const initial=window.setTimeout(()=>setNow(Date.now()),0);
    return ()=>{window.clearInterval(timer);window.clearTimeout(initial);};
  },[]);

  useEffect(() => {
    const controller = new AbortController();
    request.current=controller;
    const load=async () => {
      if(busy.current || document.visibilityState==='hidden') return;
      busy.current=true;
      setLoading(true);
      try {
        const body=await fetchForecasts(sport,AbortSignal.any([controller.signal,AbortSignal.timeout(15_000)]),'library',fetch,36);
        if(!controller.signal.aborted) {
          setLibrary(previous=>body.revision && previous?.revision===body.revision && previous.total_count===body.total_count ? {...previous,
            generated_at:body.generated_at,signals:[...new Map([...previous.signals,...body.signals].map(p=>[p.id,p])).values()]} : body);
          setError('');
        }
      } catch {
        if(!controller.signal.aborted) setError('Refresh unavailable. Previously loaded forecasts remain visible; quote freshness still applies.');
      } finally {
        busy.current=false;
        if(!controller.signal.aborted) setLoading(false);
      }
    };
    const initial=window.setTimeout(load,0);
    const poll=window.setInterval(load,60_000);
    document.addEventListener('visibilitychange',load);
    return () => {window.clearTimeout(initial);window.clearInterval(poll);document.removeEventListener('visibilitychange',load);controller.abort();};
  }, [sport,refresh]);

  async function loadMore() {
    const controller=request.current,cursor=library?.cursor;
    if(!controller || controller.signal.aborted || !cursor || cursor.offset>=1000 || busy.current) return;
    busy.current=true;setLoading(true);
    try {
      const body=await fetchForecasts(sport,AbortSignal.any([controller.signal,AbortSignal.timeout(15_000)]),'library',fetch,Math.min(1000,cursor.offset+300),cursor);
      if(controller.signal.aborted) return;
      setLibrary(previous=>previous && previous.revision===body.revision ? {...body,
        signals:[...new Map([...previous.signals,...body.signals].map(p=>[p.id,p])).values()],
        games:[...new Map([...previous.games,...body.games].map(g=>[g.sport+':'+g.game_id,g])).values()],
        invalid_signals:previous.invalid_signals+body.invalid_signals} : previous);
      setError('');
    } catch {
      if(!controller.signal.aborted) setError('More forecasts could not be loaded. The published window may have changed; use Refresh to start from the latest records. Your loaded research remains visible.');
    } finally {busy.current=false;if(!controller.signal.aborted)setLoading(false);}
  }

  const leagueProps=PROP_TYPES.filter(p=>sport==='nfl' ? ['pass_yds','pass_tds','rush_yds','rec_yds','receptions'].includes(p) : !['pass_yds','pass_tds','rush_yds','rec_yds','receptions'].includes(p));
  const effectivePropFilter=leagueProps.includes(propFilter as PropType) ? propFilter : 'all';
  const currentProps=publicSignals(allProps,now).signals;
  const effectiveWindow=windowFilter==='latest' ? latestForecastWindow(currentProps,now) : windowFilter;
  const players=[...new Map(currentProps.map(p=>[p.player,p])).values()];
  const selected=currentProps.find(p=>p.id===selectedId && p.sport===sport);
  const props = currentProps.filter(p => {
    if (p.sport !== sport) return false;
    if(scope==='saved' && !shortlist.includes(`${p.sport}:${p.player}`)) return false;
    if(scope==='eligible' && p.gated) return false;
    if(effectiveWindow!=='all' && forecastWindow(p,now)!==effectiveWindow) return false;
    if (playerFilter && !p.player.toLowerCase().includes(playerFilter.toLowerCase())) return false;
    if (effectivePropFilter !== 'all' && p.prop_type !== effectivePropFilter) return false;
    if (minEV>0 && p.ev_pct < minEV / 100) return false;
    return true;
  }).sort((a,b)=>sort==='quality' ? Number(a.gated)-Number(b.gated) || compareQuality(a,b) : sort==='player' ? a.player.localeCompare(b.player) : sort==='sample' ? (b.sample_size ?? 0)-(a.sample_size ?? 0) : b.ev_pct-a.ev_pct);
  const propGroups=groupAlternateLines(props);

  if (loading && !allProps.length) return <ForecastSkeleton />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
      <div className={styles.forecastHeading}>
        <div><h2>Player board</h2><p>One primary threshold per market, with every alternate line kept within reach.</p></div>
        <button className={styles.uxButton} type="button" onClick={()=>setRefresh(n=>n+1)} disabled={loading} aria-label="Refresh forecasts"><RefreshCw size={16} />{loading?'Refreshing...':'Refresh'}</button>
      </div>
      {coverageNotice && <p role="status" style={{padding:'8px 20px',color:'var(--text-secondary)'}}>{coverageNotice}</p>}
      {library?.cursor && library.cursor.offset<1000 && <div style={{padding:'0 20px 12px'}}><button className={styles.uxButton} type="button" disabled={loading} onClick={()=>void loadMore()}>{loading ? 'Loading forecasts...' : 'Load more recorded forecasts'}</button></div>}
      <div className={styles.forecastControls}>
        <input aria-label="Search player" className="term-input" placeholder="Find a player..." value={playerFilter} onChange={e=>{setPlayerFilter(e.target.value);setVisibleCount(24);}} />
        <select aria-label="Forecast window" className="term-select" value={windowFilter} onChange={e=>{setWindowFilter(e.target.value);setVisibleCount(24);}}><option value="latest">Available forecasts</option><option value="upcoming">Upcoming games</option><option value="archive">Past games</option><option value="all">All recorded forecasts</option></select>
        <button className={styles.uxButton} type="button" aria-pressed={scope==='saved'} onClick={()=>setScope(scope==='saved'?'all':'saved')}><Bookmark size={16} />Saved players</button>
        <details className={styles.forecastFilters}>
          <summary>Filters{effectivePropFilter!=='all' || minEV>0 || scope==='eligible' ? ' - Active' : ''}</summary>
          <div className={styles.filterFields}>
            <label>Prop<select aria-label="Prop type" className="term-select" value={effectivePropFilter} onChange={e=>setPropFilter(e.target.value)}><option value="all">All props</option>{leagueProps.map(p=><option key={p} value={p}>{PROP_LABELS[p]}</option>)}</select></label>
            <label>Eligibility<select aria-label="Forecast shortlist" className="term-select" value={scope} onChange={e=>setScope(e.target.value)}><option value="all">All estimates</option><option value="saved">Saved players</option><option value="eligible">Research eligible</option></select></label>
            <label>Sort<select aria-label="Sort forecasts" className="term-select" value={sort} onChange={e=>setSort(e.target.value)}><option value="quality">Strongest supported margin</option><option value="edge">Point-estimate edge</option><option value="sample">Largest sample</option><option value="player">Player A-Z</option></select></label>
            <label htmlFor="prop-min-edge">Minimum edge: {minEV}pp<input id="prop-min-edge" aria-valuetext={`${minEV} percentage points`} type="range" min={0} max={20} step={1} value={minEV} onChange={e=>setMinEV(Number(e.target.value))} /></label>
            <button className={styles.uxButton} type="button" onClick={resetFilters}>Reset filters</button>
          </div>
        </details>
        <div className={styles.viewSwitch} aria-label="Forecast view"><button type="button" aria-pressed={view==='cards'} onClick={()=>setView('cards')}><LayoutGrid size={16} />Cards</button><button type="button" aria-pressed={view==='table'} onClick={()=>setView('table')}><List size={16} />Table</button></div>
      </div>
      <div className={styles.forecastSummary} role="status"><span>{propGroups.length} player markets / {props.length} recorded lines / {new Set(props.map(p=>p.player)).size} players</span><span>{propGroups.filter(group=>!group.pick.gated).length} research eligible</span></div>
      {storageNotice && <p role="status" className={styles.forecastIntro}>{storageNotice}</p>}

      {error && <div className={styles.notice} role="alert">{error}</div>}
      {props.length>0 && props.every(p=>forecastWindow(p,now)==='archive') && <div className={styles.archiveNotice}><strong>Past games · Prices expired</strong><span>Original forecasts and player history remain available for research.</span></div>}
      {players.length>0 && <nav className={styles.playerShelf} aria-label="Players with recorded forecasts">{players.map(p=><button type="button" key={p.player} aria-pressed={playerFilter===p.player} onClick={()=>{setPlayerFilter(playerFilter===p.player?'':p.player);setVisibleCount(24);}}><PlayerPortrait signal={p} /><strong>{p.player}</strong><small>{p.player_profile?.team ?? p.availability?.team ?? sport.toUpperCase()}{p.player_profile?.jersey ? ` · #${p.player_profile.jersey}` : ''}{p.player_profile?.position ? ` · ${p.player_profile.position}` : ''}</small></button>)}</nav>}
      <p className={styles.forecastIntro}>Prices are recorded observations, not live quotes. Quotes expire after five minutes. Saved players stay in this browser.</p>
      {selected && <PredictionEvidence signal={selected} onClose={()=>{setSelectedId(null);document.getElementById(`forecast-${selected.id}`)?.focus();}} />}

      {/* Table */}
      <div style={{ overflowX: 'auto' }} tabIndex={0} aria-label="Recorded player prop estimates">
        {props.length === 0 ? (
          <div className={styles.propsEmpty}>
            <strong>{!allProps.length && error ? 'Forecasts could not be loaded.' : scope==='saved' ? 'Your saved-player view is empty.' : allProps.length ? 'No forecasts match these filters.' : `No recorded ${sport.toUpperCase()} forecasts are published yet.`}</strong>
            <span>{!allProps.length && error ? 'Try Refresh. A failed request does not mean there are no forecasts.' : scope==='saved' ? 'Use the bookmark next to a player to save them. Other filters still apply to your saved players.' : allProps.length ? 'Try all recorded forecasts, another player, or a lower minimum edge.' : 'The scheduled scan covers the next 48 hours, subject to source availability and the API budget. Forecasts require real pregame prices and sufficient player history.'}</span>
            {allProps.length>0 && <button className={styles.uxButton} type="button" onClick={()=>{resetFilters();setWindowFilter('all');}}>Show all forecasts</button>}
          </div>
        ) : view==='cards' ? <><div className={styles.forecastGrid}>{propGroups.slice(0,visibleCount).map(({pick:p,alternatives})=><motion.article key={p.id} className={styles.forecastCard} initial={reduceMotion ? false : {opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:.2}}>
          <div className={styles.playerHeading}><PlayerPortrait signal={p} /><div><button id={`forecast-${p.id}`} type="button" className={styles.forecastPlayer} onClick={()=>setSelectedId(p.id)}>{p.player}<span>Explore forecast →</span></button><small>{p.player_profile?.team ?? p.availability?.team ?? p.sport.toUpperCase()}{p.player_profile?.jersey ? ` · #${p.player_profile.jersey}` : ''}{p.player_profile?.position ? ` · ${p.player_profile.position}` : ''}</small></div><SaveButton prop={p} saved={shortlist.includes(`${p.sport}:${p.player}`)} onSave={()=>savePlayer(p)} /></div>
          <h3>{p.direction} {p.line} <span>{PROP_LABELS[p.prop_type]}</span></h3>
          <p className={styles.cardMatchup}><time dateTime={p.game_start_time}>{new Date(p.game_start_time ?? '').toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</time><br />{p.home_team} vs {p.away_team} | <QuoteAge signal={p} now={now} /></p>
          <ProbabilityComparison model={p.true_prob} implied={p.implied_prob} gated={p.gated} />
          <div className={styles.cardFooter}><span className={`badge ${p.gated ? 'badge-dim' : 'badge-mint'}`}>{forecastWindow(p,now)==='archive' ? 'Historical forecast' : p.gated ? 'Blocked estimate' : 'Research eligible'}</span><span>{p.sample_size} games · {p.sportsbook}</span></div>
          {p.gated && <p className={styles.cardGate}>{REASONS[p.gate_reason ?? ''] ?? 'A model or portfolio risk gate blocked this pick.'}</p>}
          <AlternateLines alternatives={alternatives} now={now} onExplain={setSelectedId} />
        </motion.article>)}</div>{propGroups.length>visibleCount && <div className={styles.moreForecasts}><button type="button" className={styles.uxButton} onClick={()=>setVisibleCount(n=>n+24)}>Show 24 more / {propGroups.length-visibleCount} markets remaining</button></div>}</> : <table className="data-table">
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
            {propGroups.map(({pick:p,alternatives}) => <PropRow key={p.id} prop={p} alternatives={alternatives} onExplain={id=>setSelectedId(id ?? p.id)} saved={shortlist.includes(`${p.sport}:${p.player}`)} onSave={()=>savePlayer(p)} now={now} />)}
          </tbody>
        </table>}
      </div>
    </div>
  );
}

function ForecastSkeleton() {
  return <div className={styles.forecastSkeleton} role="status" aria-label="Loading recorded prop estimates"><div className={styles.skeletonHeading} /><div className={styles.skeletonControls} /><div className={styles.skeletonCards}>{[0,1,2].map(item=><div key={item}><span /><span /><span /><b /></div>)}</div></div>;
}

function AlternateLines({alternatives,now,onExplain}:{alternatives:EVSignal[];now:number;onExplain:(id:string)=>void}) {
  if(!alternatives.length) return null;
  return <details className={styles.alternateLines}><summary>{alternatives.length} alternate {alternatives.length===1 ? 'line' : 'lines'}</summary><div>{alternatives.map(option=><button key={option.id} type="button" onClick={()=>onExplain(option.id)}><span><strong>{option.direction} {option.line}</strong> {PROP_LABELS[option.prop_type]}</span><span>{option.sportsbook} / {option.american_odds>0?'+':''}{option.american_odds}</span><span>{(option.true_prob*100).toFixed(1)}% model / <QuoteAge signal={option} now={now} /></span></button>)}</div></details>;
}

function SaveButton({prop,saved,onSave}:{prop:EVSignal;saved:boolean;onSave:()=>void}) {
  return <button type="button" className={styles.savePlayer} aria-label={`${saved?'Unsave':'Save'} ${prop.player}`} aria-pressed={saved} onClick={onSave}><Bookmark size={18} fill={saved?'currentColor':'none'} /></button>;
}

function PropRow({ prop,alternatives,onExplain,saved,onSave,now }: { prop: EVSignal;alternatives:EVSignal[];onExplain:(id?:string)=>void;saved:boolean;onSave:()=>void;now:number }) {
  const evPct = prop.ev_pct * 100;
  return (
    <tr>
      <td>
        <div className={styles.playerHeading}><PlayerPortrait signal={prop} /><SaveButton prop={prop} saved={saved} onSave={onSave} /></div>
        <button id={`forecast-${prop.id}`} type="button" className={styles.forecastPlayer} onClick={()=>onExplain()}>{prop.player}<span>Why this forecast →</span></button>
        <div style={{color:'var(--text-secondary)',fontSize:12}}>{prop.player_profile?.team ?? prop.availability?.team ?? prop.sport.toUpperCase()}{prop.player_profile?.jersey ? ` · #${prop.player_profile.jersey}` : ''}{prop.player_profile?.position ? ` · ${prop.player_profile.position}` : ''}</div>
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
        <AlternateLines alternatives={alternatives} now={now} onExplain={onExplain} />
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
