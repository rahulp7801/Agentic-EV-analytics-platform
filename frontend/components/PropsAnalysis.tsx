'use client';
import { useState, useEffect } from 'react';
import type { Sport, PropType, EVSignal } from '@/lib/types';

// PropAnalysis is derived from real EV signals — no mock data
interface PropsAnalysisProps { sport: Sport; }

const PROP_TYPES: PropType[] = ['points', 'rebounds', 'assists', 'threes', 'pra', 'pass_yds', 'pass_tds', 'rush_yds', 'rec_yds'];

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

  useEffect(() => {
    fetch('/api/signals', { cache: 'no-store' })
      .then(r => r.json())
      .then(data => {
        setAllProps(Array.isArray(data.signals) ? data.signals : []);
      })
      .catch(() => setAllProps([]))
      .finally(() => setLoading(false));
  }, [sport]);

  const props = allProps.filter(p => {
    if (p.sport !== sport) return false;
    if (playerFilter && !p.player.toLowerCase().includes(playerFilter.toLowerCase())) return false;
    if (propFilter !== 'all' && p.prop_type !== propFilter) return false;
    if (p.ev_pct < minEV / 100) return false;
    return true;
  });

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 10 }}>
      <span className="live-dot" style={{ width: 8, height: 8 }} />
      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Loading from pipeline...</span>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px',
        borderBottom: '1px solid var(--border-dim)',
        background: 'var(--bg-base)',
        display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
      }}>
        <div className="section-header">Prop Analysis</div>
        <div style={{ flex: 1 }} />

        <input
          className="term-input"
          style={{ width: 180 }}
          placeholder="Search player..."
          value={playerFilter}
          onChange={e => setPlayerFilter(e.target.value)}
        />
        <select className="term-select" value={propFilter} onChange={e => setPropFilter(e.target.value)}>
          <option value="all">All Props</option>
          {PROP_TYPES.map(p => <option key={p} value={p}>{p.replace('_', ' ').toUpperCase()}</option>)}
        </select>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 10, whiteSpace: 'nowrap' }}>Min edge (pp)</span>
          <input
            type="range" min={0} max={20} step={1} value={minEV}
            onChange={e => setMinEV(Number(e.target.value))}
            style={{ width: 80, accentColor: 'var(--accent-mint)' }}
          />
          <span style={{ color: 'var(--accent-mint)', fontSize: 10, fontWeight: 600, minWidth: 30 }}>
            {minEV}pp
          </span>
        </div>
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table className="data-table">
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
            {props.map(p => <PropRow key={p.id} prop={p} />)}
            {props.length === 0 && (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '32px 0' }}>
                  No props match current filters
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PropRow({ prop }: { prop: EVSignal }) {
  const evPct = prop.ev_pct * 100;
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 12 }}>{prop.player}</div>
        <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>{prop.team} vs {prop.opponent}</div>
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
        }}>+{evPct.toFixed(1)}pp</span>
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
