'use client';
import { useState, useEffect } from 'react';
import type { Sport, PropType, EVSignal } from '@/lib/types';
import styles from './ResearchViews.module.css';
import PredictionEvidence from './PredictionEvidence';
import {forecastWindow,publicSignals} from '@/lib/signalMetrics';

// PropAnalysis is derived from real EV signals — no mock data
interface PropsAnalysisProps { sport: Sport; }

const PROP_TYPES: PropType[] = ['points', 'rebounds', 'assists', 'threes', 'pra', 'steals', 'blocks', 'pass_yds', 'pass_tds', 'rush_yds', 'rec_yds', 'receptions'];

function ProbabilityComparison({ model, implied }: { model: number; implied: number }) {
  const edge = model - implied;
  return (
    <div style={{ minWidth: 160 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ fontSize: 9, color: 'var(--accent-cyan)' }}>MODEL {(model * 100).toFixed(0)}%</span>
        <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>BOOK {(implied * 100).toFixed(0)}%</span>
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
          background: edge > 0 ? 'var(--accent-mint)' : 'var(--accent-red)',
          opacity: 0.7,
        }} />
      </div>
      <div style={{ textAlign: 'right', marginTop: 2 }}>
        <span style={{
          fontSize: 9, fontWeight: 600,
          color: edge > 0 ? 'var(--accent-mint)' : 'var(--accent-red)',
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
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 3 }}>
        {ci ? `95% CI: [${(ci[0] * 100).toFixed(0)}%, ${(ci[1] * 100).toFixed(0)}%]` : "Uncertainty unavailable"}
      </div>
      <div style={{ fontSize: 9, color: 'var(--text-secondary)' }}>
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

  useEffect(()=>{
    const timer=window.setInterval(()=>setNow(Date.now()),30_000);
    const initial=window.setTimeout(()=>setNow(Date.now()),0);
    return ()=>{window.clearInterval(timer);window.clearTimeout(initial);};
  },[]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError('');
      fetch(`/api/signals?sport=${sport}`, { cache: 'no-store', signal: controller.signal })
        .then(async response => {
          const body = await response.json();
          if (!response.ok) throw new Error(body.error || 'Recorded prop estimates unavailable.');
          return body;
        })
        .then(data => {
          if (!controller.signal.aborted) setAllProps(Array.isArray(data.signals) ? data.signals : []);
        })
        .catch(loadError => {
          if (!controller.signal.aborted) {
            setAllProps([]);
            setError(loadError instanceof Error ? loadError.message : 'Recorded prop estimates unavailable.');
          }
        })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [sport]);

  const currentProps=publicSignals(allProps,now).signals;
  const selected=currentProps.find(p=>p.id===selectedId && p.sport===sport);
  const props = currentProps.filter(p => {
    if (p.sport !== sport) return false;
    if(windowFilter!=='all' && forecastWindow(p,now)!==windowFilter) return false;
    if (playerFilter && !p.player.toLowerCase().includes(playerFilter.toLowerCase())) return false;
    if (propFilter !== 'all' && p.prop_type !== propFilter) return false;
    if (minEV>0 && p.ev_pct < minEV / 100) return false;
    return true;
  });

  if (loading) return (
    <div className={styles.loadingState}>
      <div className={styles.loadingPanel}>
        <span className="live-dot" style={{ width: 8, height: 8 }} />
        <span>Loading recorded prop estimates…</span>
      </div>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div className={styles.propsHeader}>
        <div className="section-header">Player forecasts</div>
        <div style={{ flex: 1 }} />

        <input
          id="prop-player-filter"
          aria-label="Search player"
          className="term-input"
          style={{ width: 180 }}
          placeholder="Search player..."
          value={playerFilter}
          onChange={e => setPlayerFilter(e.target.value)}
        />
        <select aria-label="Forecast window" className="term-select" value={windowFilter} onChange={e=>setWindowFilter(e.target.value)}>
          <option value="upcoming">Upcoming games</option><option value="archive">Past games</option><option value="all">All recorded forecasts</option>
        </select>
        <select id="prop-type-filter" aria-label="Prop type" className="term-select" value={propFilter} onChange={e => setPropFilter(e.target.value)}>
          <option value="all">All Props</option>
          {PROP_TYPES.map(p => <option key={p} value={p}>{p.replace('_', ' ').toUpperCase()}</option>)}
        </select>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <label htmlFor="prop-min-edge" style={{ color: 'var(--text-muted)', fontSize: 10, whiteSpace: 'nowrap' }}>Min edge (pp)</label>
          <input
            id="prop-min-edge"
            aria-valuetext={`${minEV} percentage points`}
            type="range" min={0} max={20} step={1} value={minEV}
            onChange={e => setMinEV(Number(e.target.value))}
            style={{ width: 80, accentColor: 'var(--accent-mint)' }}
          />
          <span style={{ color: 'var(--accent-mint)', fontSize: 10, fontWeight: 600, minWidth: 30 }}>
            {minEV}pp
          </span>
        </div>
      </div>

      {error && <div className={styles.notice} role="alert">{error}</div>}
      <p className={styles.forecastIntro}>Historical model forecasts with observed prices. Open a player to see the reasoning, uncertainty and current injury evidence. Blocked estimates are retained for transparency.</p>
      {selected && <PredictionEvidence signal={selected} onClose={()=>{setSelectedId(null);document.getElementById(`forecast-${selected.id}`)?.focus();}} />}

      {/* Table */}
      <div style={{ flex: 1, overflow: 'auto' }} tabIndex={0} aria-label="Recorded player prop estimates">
        {props.length === 0 ? (
          <div className={styles.propsEmpty}>
            <strong>{allProps.length ? 'No forecasts match these filters.' : `No recorded ${sport.toUpperCase()} forecasts are published yet.`}</strong>
            <span>{allProps.length ? 'Try all recorded forecasts, another player, or a lower minimum edge.' : 'The scheduled scan covers the next 48 hours, subject to source availability and the API budget. Forecasts require real pregame prices and sufficient player history.'}</span>
          </div>
        ) : <table className="data-table">
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
            {props.map(p => <PropRow key={p.id} prop={p} onExplain={()=>setSelectedId(p.id)} />)}
          </tbody>
        </table>}
      </div>
    </div>
  );
}

function PropRow({ prop,onExplain }: { prop: EVSignal;onExplain:()=>void }) {
  const evPct = prop.ev_pct * 100;
  return (
    <tr>
      <td>
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
        <ProbabilityComparison model={prop.true_prob} implied={prop.implied_prob} />
      </td>
      <td>
        <span style={{
          color: evPct >= 10 ? 'var(--accent-mint)' : evPct >= 5 ? 'var(--accent-amber)' : 'var(--text-secondary)',
          fontWeight: 700, fontSize: 13,
        }}>{evPct>0?'+':''}{evPct.toFixed(1)}pp</span>
      </td>
      <td>
        <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>
          {(prop.kelly_fraction * 100).toFixed(1)}%
        </span>
        <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>of bankroll</div>
      </td>
      <td>
        <ConfidenceBar ci={prop.confidence_interval ?? null} mean={prop.mean_stat ?? null} line={prop.line} />
        <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>n={prop.sample_size}</div>
      </td>
      <td>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span className="badge badge-dim">{prop.sportsbook}</span>
          <span style={{ color: 'var(--text-secondary)', fontSize: 11, fontWeight: 600 }}>
            {prop.american_odds > 0 ? '+' : ''}{prop.american_odds}
          </span>
        </div>
      </td>
    </tr>
  );
}
