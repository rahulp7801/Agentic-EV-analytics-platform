'use client';
import Performance from "@/components/Performance";
import { useState, useEffect, useCallback } from 'react';
import type { EVSignal, Sport } from '@/lib/types';

interface EVDashboardProps {
  sport: Sport;
  onAddToParlay?: (s: EVSignal) => void;
  parlayIds?: Set<string>;
}

interface CachedGame {
  game_id: string;
  home_team: string;
  away_team: string;
  date: string;
  sport?: Sport;
}

interface ESPNGame {
  home_abbr: string;
  away_abbr: string;
  home_name: string;
  away_name: string;
  date: string;
  label: string;
  game_time: string;
}

interface SignalCache {
  generated_at: string | null;
  game: { home_team: string; away_team: string; date: string } | null;
  games?: CachedGame[];
  signals: EVSignal[];
  error?: string;
  scan_note?: string;
}

type RichSignal = EVSignal;

function fmt_pct(n: number) { return (n * 100).toFixed(1) + '%'; }
function fmt_odds(n: number) { return n > 0 ? '+' + n : String(n); }
function time_ago(iso: string) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function buildMispricingReason(signal: RichSignal): [string, string, string] {
  return [
    `${signal.direction.toUpperCase()} ${signal.line}: ${(signal.true_prob * 100).toFixed(1)}% estimated win probability.`,
    signal.expected_return == null ? 'Expected return unavailable.' : `${(signal.expected_return * 100).toFixed(1)}% expected return per unit stake at the quoted payout.`,
    `Sample: ${signal.sample_size ?? 'unknown'} games. ${signal.gated ? `Gated: ${signal.gate_reason ?? 'risk policy'}.` : 'Estimate has not been validated by settled results.'}`,
  ];
}

function KellyBar({ fraction }: { fraction: number }) {
  const pct = fraction * 100;
  const color = pct >= 10 ? 'var(--accent-mint)' : pct >= 5 ? 'var(--accent-amber)' : 'var(--text-secondary)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 120 }}>
      <div className="prob-track" style={{ flex: 1 }}>
        <div className="prob-fill" style={{ width: `${Math.min(pct / 25 * 100, 100)}%`, background: color }} />
      </div>
      <span style={{ color, fontWeight: 600, fontSize: 11, minWidth: 36, textAlign: 'right' }}>
        {pct > 0 ? pct.toFixed(1) + '%' : 'GATED'}
      </span>
    </div>
  );
}

function EVSignalRow({ signal, onSelect }: { signal: RichSignal; onSelect: (s: EVSignal) => void }) {
  const evPct = signal.ev_pct * 100;
  const evColor = evPct >= 15 ? 'var(--accent-mint)' : evPct >= 8 ? 'var(--accent-amber)' : 'var(--text-secondary)';

  return (
    <tr
      className={signal.strength === 'high' ? 'row-highlight-mint' : ''}
      style={{ cursor: 'pointer' }}
      onClick={() => onSelect(signal)}
    >
      <td>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {signal.strength === 'high' && <span className="live-dot" style={{ width: 6, height: 6, flexShrink: 0 }} />}
          <div>
            <div style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 12 }}>{signal.player}</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>
              {signal.team} vs {signal.opponent}
            </div>
          </div>
        </div>
      </td>
      <td>
        <span className="badge badge-blue">NBA</span>
        {signal.gated && (
          <span className="badge badge-amber" style={{ marginLeft: 4 }}>GATED</span>
        )}
      </td>
      <td>
        <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
          {signal.prop_type.replace('_', ' ').toUpperCase()}
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>
          {signal.direction.toUpperCase()} {signal.line} · {fmt_odds(signal.american_odds)}
        </div>
      </td>
      <td>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div>
            <div style={{ color: 'var(--accent-cyan)', fontWeight: 600, fontSize: 12 }}>{fmt_pct(signal.true_prob)}</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>model</div>
          </div>
          <div style={{ color: 'var(--text-dim)' }}>→</div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{fmt_pct(signal.implied_prob)}</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>implied</div>
          </div>
        </div>
      </td>
      <td>
        <span style={{ color: evColor, fontWeight: 700, fontSize: 13 }}>+{evPct.toFixed(1)}pp</span>
      </td>
      <td><KellyBar fraction={signal.kelly_fraction} /></td>
      <td>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span className="badge badge-dim">{signal.sportsbook}</span>
          {signal.sample_size != null && (
            <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>
              n={signal.sample_size} · μ={signal.mean_stat?.toFixed(1)}
            </span>
          )}
        </div>
      </td>
    </tr>
  );
}

function SignalDetailPanel({ signal, onClose, onAddToParlay, inParlay }: {
  signal: RichSignal;
  onClose: () => void;
  onAddToParlay?: (s: EVSignal) => void;
  inParlay?: boolean;
}) {
  const evPct = signal.ev_pct * 100;
  const kellyPct = signal.kelly_fraction * 100;
  const mispricingReasons = buildMispricingReason(signal);

  return (
    <div style={{
      position: 'absolute', right: 0, top: 0, bottom: 0, width: 340,
      background: 'var(--bg-card)', borderLeft: '1px solid var(--border-mid)',
      display: 'flex', flexDirection: 'column', zIndex: 10,
    }}>
      {/* Header */}
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border-dim)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexShrink: 0 }}>
        <div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>
            {signal.player}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              {signal.prop_type.replace('_', ' ').toUpperCase()}
            </span>
            <span style={{
              fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 2,
              background: signal.direction === 'under' ? 'rgba(0,180,255,0.15)' : 'rgba(0,229,160,0.12)',
              color: signal.direction === 'under' ? 'var(--accent-cyan)' : 'var(--accent-mint)',
            }}>
              {(signal.direction || 'over').toUpperCase()} {signal.line}
            </span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{signal.team} vs {signal.opponent}</span>
          </div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 16 }}>✕</button>
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {/* Metrics grid */}
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border-dim)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {[
              ['EDGE (pp)', '+' + evPct.toFixed(1) + 'pp', 'var(--accent-mint)'],
              ['KELLY STAKE', signal.gated ? 'GATED' : kellyPct.toFixed(1) + '%', signal.gated ? 'var(--accent-amber)' : 'var(--accent-cyan)'],
              ['EXPECTED RETURN', signal.expected_return == null ? 'Unavailable' : (signal.expected_return * 100).toFixed(1) + '%', 'var(--accent-mint)'],
              ['MODEL PROB', (signal.true_prob * 100).toFixed(1) + '%', 'var(--text-primary)'],
              ['BOOK IMPLIED', (signal.implied_prob * 100).toFixed(1) + '%', 'var(--text-secondary)'],
            ].map(([label, value, color]) => (
              <div key={label} style={{ padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-dim)', borderRadius: 3 }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 4 }}>{label}</div>
                <div style={{ color, fontWeight: 700, fontSize: 15, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
              </div>
            ))}
          </div>
          {signal.sample_size != null && (
            <div style={{ marginTop: 8, padding: '6px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-dim)', borderRadius: 3 }}>
              <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>HISTORICAL BASE · </span>
              <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>n={signal.sample_size} games · mean {signal.mean_stat?.toFixed(1)}</span>
            </div>
          )}
        </div>

        {/* Line + source */}
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-dim)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Line</span>
            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{signal.direction.toUpperCase()} {signal.line}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Source</span>
            <span className="badge badge-dim">{signal.sportsbook}</span>
          </div>
          {signal.gated && (
            <div style={{ marginTop: 8, padding: '6px 10px', background: 'rgba(245,166,35,0.06)', border: '1px solid rgba(245,166,35,0.2)', borderRadius: 3, fontSize: 10, color: 'var(--accent-amber)' }}>
              ⚠ Gated by daily drawdown cap. Signal is valid — exposure budget exhausted for today.
            </div>
          )}
        </div>

        {/* Context Signals — explicit structured section */}
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-dim)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
            <div className="section-header">Context Signals</div>
            <span style={{ fontSize: 9, color: 'var(--text-dim)', padding: '1px 5px', border: '1px solid var(--border-dim)', borderRadius: 2 }}>LIVE DB</span>
          </div>
          {/* Opponent Defense */}
          {signal.opponent_def_rating != null ? (
            <div style={{ padding: '8px 10px', marginBottom: 6, background: 'var(--bg-surface)', border: '1px solid var(--border-dim)', borderRadius: 3 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.08em' }}>OPP DEFENSIVE RATING</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>{signal.opponent_def_rating.toFixed(1)}</span>
              </div>
              {(() => {
                const delta = signal.opponent_def_rating - 115.0;
                const isStrongD = delta < -1;
                const isWeakD = delta > 1;
                const overFavorable = isWeakD;
                const underFavorable = isStrongD;
                const isOver = (signal.direction || 'over') === 'over';
                const favorable = isOver ? overFavorable : underFavorable;
                const risk = isOver ? isStrongD : isWeakD;
                return (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>vs league avg 115.0 ({delta > 0 ? '+' : ''}{delta.toFixed(1)})</span>
                    {favorable && <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2, background: 'rgba(0,229,160,0.12)', color: 'var(--accent-mint)', fontWeight: 600 }}>FAVORABLE</span>}
                    {risk && <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2, background: 'rgba(255,80,80,0.12)', color: 'var(--accent-red)', fontWeight: 600 }}>RISK FACTOR</span>}
                    {!favorable && !risk && <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>NEUTRAL</span>}
                  </div>
                );
              })()}
            </div>
          ) : (
            <div style={{ padding: '6px 10px', marginBottom: 6, background: 'var(--bg-surface)', border: '1px solid var(--border-dim)', borderRadius: 3, fontSize: 10, color: 'var(--text-dim)' }}>
              Defensive rating unavailable
            </div>
          )}
          {/* Rest + Venue row */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
            {signal.rest_days != null && (
              <div style={{ flex: 1, padding: '6px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-dim)', borderRadius: 3 }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 3 }}>REST</div>
                <span style={{
                  fontSize: 10, fontWeight: 600,
                  color: signal.rest_days === 0 ? 'var(--accent-red)' : signal.rest_days >= 3 ? 'var(--accent-mint)' : 'var(--text-secondary)',
                }}>
                  {signal.rest_days === 0 ? 'B2B — FATIGUE' : signal.rest_days === 1 ? '1 day rest' : `${signal.rest_days} days rest`}
                </span>
              </div>
            )}
            {signal.is_home != null && (
              <div style={{ flex: 1, padding: '6px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-dim)', borderRadius: 3 }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 3 }}>VENUE</div>
                <span style={{ fontSize: 10, fontWeight: 600, color: signal.is_home ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>
                  {signal.is_home ? 'HOME (+1.5pp boost)' : 'AWAY'}
                </span>
              </div>
            )}
          </div>
          {/* Inactive teammates from injury_flags */}
          {signal.injury_flags && Object.keys(signal.injury_flags).length > 0 && (
            <div style={{ padding: '6px 10px', background: 'rgba(245,166,35,0.05)', border: '1px solid rgba(245,166,35,0.2)', borderRadius: 3 }}>
              <div style={{ fontSize: 9, color: 'var(--accent-amber)', letterSpacing: '0.08em', marginBottom: 4 }}>INACTIVE TEAMMATES</div>
              {Object.entries(signal.injury_flags).map(([name, status]) => (
                <div key={name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-secondary)', marginBottom: 2 }}>
                  <span>{name}</span>
                  <span style={{ color: 'var(--accent-amber)', fontSize: 9 }}>{status}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Trade Plan */}
        <div style={{ padding: '12px 16px' }}>
          <div className="section-header" style={{ marginBottom: 10 }}>Trade Plan</div>
          {signal.trade_plan.map((bullet, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 8, padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-dim)', borderRadius: 3 }}>
              <span style={{ color: 'var(--accent-mint)', fontWeight: 700, fontSize: 10, flexShrink: 0, marginTop: 1 }}>
                {String.fromCharCode(65 + i)}
              </span>
              <span style={{ color: 'var(--text-secondary)', fontSize: 11, lineHeight: 1.5 }}>{bullet}</span>
            </div>
          ))}
          {onAddToParlay && (
            <button
              onClick={() => onAddToParlay(signal)}
              className={inParlay ? 'btn-ghost' : 'btn-mint'}
              style={{ width: '100%', marginTop: 8, fontSize: 11, padding: '7px 0', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
            >
              {inParlay ? '✓ Added to Parlay Builder' : '+ Add to Parlay Builder'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function EVDashboard({ sport, onAddToParlay, parlayIds = new Set() }: EVDashboardProps) {
  const [data, setData] = useState<SignalCache | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<EVSignal | null>(null);
  const [filter, setFilter] = useState<'all' | 'eligible' | 'gated'>('all');
  const [sortBy, setSortBy] = useState<'ev' | 'kelly' | 'prob'>('ev');
  // Game picker
  const [espnGames, setEspnGames] = useState<ESPNGame[]>([]);
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null);

  const fetchSignals = useCallback(async () => {
    try {
      const res = await fetch('/api/signals', { cache: 'no-store' });
      const json = await res.json();
      setData(json);

    } catch {
      setData({ generated_at: null, game: null, signals: [], error: 'Failed to fetch signals' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSignals();
    // Fetch ESPN schedule for the game picker
    fetch(`/api/games?sport=${sport}`, { cache: 'no-store' })
      .then(r => r.json())
      .then(d => setEspnGames(d.games || []))
      .catch(() => {});
  }, [fetchSignals, sport]);

  useEffect(() => { setSelectedGameId(null); }, [sport]);
  useEffect(() => {
    const timer = setInterval(fetchSignals, 30000);
    return () => clearInterval(timer);
  }, [fetchSignals]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchSignals();
    setRefreshing(false);
  };

  // Merge cached games + ESPN games into a unified picker list (deduped by game_id)
  const _allPickerGames: { game_id: string; label: string; away: string; home: string; date: string; cached: boolean }[] = [];
  const _seen = new Set<string>();

  for (const g of (data?.games || []).filter(g => g.sport === sport || (!g.sport && sport === 'nba'))) {
    if (!_seen.has(g.game_id)) {
      _seen.add(g.game_id);
      const hasSignals = (data?.signals || []).some(s => s.game_id === g.game_id);
      _allPickerGames.push({ game_id: g.game_id, label: g.date, away: g.away_team, home: g.home_team, date: g.date, cached: hasSignals });
    }
  }
  for (const g of espnGames) {
    const gid = `${g.home_abbr.toLowerCase()}_${g.away_abbr.toLowerCase()}_${g.date}`;
    if (!_seen.has(gid)) {
      _seen.add(gid);
      _allPickerGames.push({ game_id: gid, label: g.label, away: g.away_abbr, home: g.home_abbr, date: g.date, cached: false });
    }
  }

  // Filter signals to selected game (if any)
  const gameSignals = selectedGameId
    ? (data?.signals || []).filter(s => s.game_id === selectedGameId || !s.game_id)
    : (data?.signals || []);

  const signals = gameSignals
    .filter(s => s.sport === sport)
    .filter(s => filter === 'all' || (filter === 'gated' ? s.gated : !s.gated))
    .sort((a, b) => {
      if (sortBy === 'ev') return b.ev_pct - a.ev_pct;
      if (sortBy === 'kelly') return b.kelly_fraction - a.kelly_fraction;
      return b.true_prob - a.true_prob;
    });

  const highConf = signals.filter(s => s.confidence_interval != null).length;
  const avgEV = signals.length > 0 ? signals.reduce((sum, s) => sum + s.ev_pct, 0) / signals.length : 0;

  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12 }}>
        <span className="live-dot" style={{ width: 10, height: 10 }} />
        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Loading market estimates...</span>
      </div>
    );
  }

  if (data?.error && !data.signals.length && _allPickerGames.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 14 }}>
        <div style={{ color: 'var(--accent-amber)', fontSize: 13, fontWeight: 600 }}>Market estimates unavailable</div>
        <div style={{ color: 'var(--text-muted)', fontSize: 11, textAlign: 'center', maxWidth: 360 }}>
          Market estimates will appear after the next successful update.
        </div>
      </div>
    );
  }

  const _selGame = _allPickerGames.find(g => g.game_id === selectedGameId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', position: 'relative' }}>
      {/* Game Picker */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '7px 14px',
        borderBottom: '1px solid var(--border-dim)', background: 'var(--bg-void)',
        flexShrink: 0, flexWrap: 'wrap',
      }}>
        <span style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.12em', textTransform: 'uppercase', flexShrink: 0 }}>Game</span>
        {_allPickerGames.length === 0 ? (
          <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>No games available — checking schedule...</span>
        ) : (
          _allPickerGames.map(g => (
            <button
              key={g.game_id}
              onClick={() => setSelectedGameId(g.game_id)}
              className="btn-ghost"
              style={{
                fontSize: 10, padding: '3px 10px',
                color: selectedGameId === g.game_id ? 'var(--accent-mint)' : 'var(--text-secondary)',
                borderColor: selectedGameId === g.game_id ? 'rgba(0,229,160,0.4)' : undefined,
                display: 'flex', alignItems: 'center', gap: 5,
              }}
            >
              {g.cached && <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--accent-mint)', flexShrink: 0, display: 'inline-block' }} />}
              {g.away} @ {g.home}
              <span style={{ color: 'var(--text-dim)', fontSize: 9 }}>{g.label}</span>
            </button>
          ))
        )}
        <div style={{ flex: 1 }} />
        <button
          className="btn-ghost"
          style={{ fontSize: 9, padding: '2px 8px' }}
          onClick={handleRefresh}
          disabled={refreshing}
          title="Refresh market estimates"
        >
          {refreshing ? '● Loading...' : '↻ Refresh'}
        </button>

      </div>

      {/* Summary row */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border-dim)', background: 'var(--bg-surface)', flexShrink: 0 }}>
        <SummaryCard label="Cached estimates" value={String(signals.length)} sub="observed quotes" accent="mint" />
        <SummaryCard label="With uncertainty" value={String(highConf)} sub="reported intervals" accent="cyan" />
        <SummaryCard label="Avg probability edge" value={signals.length ? '+' + (avgEV * 100).toFixed(1) + 'pp' : '—'} sub="percentage points" accent="cyan" />
        <SummaryCard
          label="Game"
          value={_selGame ? `${_selGame.away} @ ${_selGame.home}` : (data?.game ? `${data.game.away_team} @ ${data.game.home_team}` : '—')}
          sub={_selGame?.date || data?.game?.date || ''}
        />
        <div style={{ flex: 1, padding: '10px 14px', borderRight: '1px solid var(--border-dim)', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 6 }}>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>Cache Age</div>
          <div style={{ fontSize: 11, color: data?.generated_at ? 'var(--text-secondary)' : 'var(--accent-red)' }}>
            {data?.generated_at ? time_ago(data.generated_at) : 'No cache'}
          </div>
          {data?.scan_note && (
            <div style={{ fontSize: 9, color: 'var(--accent-amber)', maxWidth: 220 }}>{data.scan_note}</div>
          )}
        </div>
      </div>

      <Performance />

      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px',
        borderBottom: '1px solid var(--border-dim)', background: 'var(--bg-base)', flexShrink: 0,
      }}>
        <div className="section-header">EV Signals · Model Estimates</div>
        <div style={{ flex: 1 }} />
        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>Filter:</span>
        {(['all', 'eligible', 'gated'] as const).map(f => (
          <button key={f} className="btn-ghost" onClick={() => setFilter(f)}
            style={{ fontSize: 10, padding: '3px 10px', color: filter === f ? 'var(--accent-mint)' : undefined, borderColor: filter === f ? 'rgba(0,229,160,0.3)' : undefined }}>
            {f.toUpperCase()}
          </button>
        ))}
        <div className="divider-v" style={{ margin: '0 4px' }} />
        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>Sort:</span>
        {([['ev', 'Edge (pp)'], ['kelly', 'Kelly'], ['prob', 'Prob']] as const).map(([key, label]) => (
          <button key={key} className="btn-ghost" onClick={() => setSortBy(key)}
            style={{ fontSize: 10, padding: '3px 10px', color: sortBy === key ? 'var(--accent-mint)' : undefined, borderColor: sortBy === key ? 'rgba(0,229,160,0.3)' : undefined }}>
            {label}
          </button>
        ))}
      </div>

      {/* Pipeline provenance notice */}
      <div style={{
        padding: '5px 14px', fontSize: 10, color: 'var(--text-dim)',
        background: 'var(--bg-void)', borderBottom: '1px solid var(--border-dim)',
        display: 'flex', gap: 8, flexShrink: 0,
      }}>
        <span style={{ color: 'var(--accent-mint)' }}>✓</span>
        Historical estimates with recorded quotes; performance requires settled outcomes.
        {data?.generated_at && <span style={{ marginLeft: 'auto' }}>Generated {new Date(data.generated_at).toLocaleString()}</span>}
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
        {signals.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '80%', gap: 10 }}>
            {_selGame && !_selGame.cached ? (
              <>
                <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>No cached signals for {_selGame.away} @ {_selGame.home}</span>
                <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>Click ⚡ Re-scan to run the pipeline for this game</span>
              </>
            ) : (
              <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>No signals match current filters</span>
            )}
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Player</th>
                <th>Sport</th>
                <th>Prop / Line</th>
                <th>Probability</th>
                <th>Edge (pp)</th>
                <th style={{ minWidth: 160 }}>Kelly Stake</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {signals.map(s => (
                <EVSignalRow key={s.id} signal={s as RichSignal} onSelect={setSelected} />
              ))}
            </tbody>
          </table>
        )}
        {selected && (
          <SignalDetailPanel
            signal={selected as RichSignal}
            onClose={() => setSelected(null)}
            onAddToParlay={onAddToParlay}
            inParlay={parlayIds.has(selected.id)}
          />
        )}
      </div>
    </div>
  );
}

function SummaryCard({ label, value, sub, accent }: { label: string; value: string; sub: string; accent?: 'mint' | 'cyan' | 'amber' }) {
  const color = accent === 'mint' ? 'var(--accent-mint)' : accent === 'cyan' ? 'var(--accent-cyan)' : accent === 'amber' ? 'var(--accent-amber)' : 'var(--text-primary)';
  return (
    <div style={{ flex: 1, padding: '10px 16px', borderRight: '1px solid var(--border-dim)' }}>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 4 }}>{label}</div>
      <div style={{ color, fontWeight: 700, fontSize: 20, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 3 }}>{sub}</div>
    </div>
  );
}
