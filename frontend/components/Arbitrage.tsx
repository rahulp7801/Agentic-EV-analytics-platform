'use client';
import { useState, useEffect, useCallback } from 'react';

function fmt_odds(n: number) { return n > 0 ? '+' + n : String(n); }
function fmt_pct(n: number) { return (n * 100).toFixed(1) + '%'; }
function time_ago(iso: string) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

interface NBAGame {
  home_abbr: string;
  away_abbr: string;
  home_name: string;
  away_name: string;
  date: string;
  label: string;
  game_time: string;
}

function GameSelector({
  games,
  selected,
  onSelect,
  scanning,
  onScan,
}: {
  games: NBAGame[];
  selected: NBAGame | null;
  onSelect: (g: NBAGame) => void;
  scanning: boolean;
  onScan: () => void;
}) {
  if (games.length === 0) {
    return (
      <div style={{
        padding: '10px 14px',
        background: 'rgba(255,180,0,0.04)',
        borderBottom: '1px solid var(--border-dim)',
        fontSize: 11, color: 'var(--text-muted)',
      }}>
        No upcoming NBA games found — ESPN may be unavailable.
      </div>
    );
  }

  return (
    <div style={{
      padding: '10px 14px',
      borderBottom: '1px solid var(--border-dim)',
      background: 'var(--bg-void)',
    }}>
      <div style={{
        fontSize: 9, color: 'var(--text-muted)',
        letterSpacing: '0.12em', marginBottom: 8, textTransform: 'uppercase',
      }}>
        Select Game to Scan
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {games.map(g => {
          const key = `${g.away_abbr}@${g.home_abbr}-${g.date}`;
          const isSelected = selected?.home_abbr === g.home_abbr &&
                             selected?.away_abbr === g.away_abbr &&
                             selected?.date === g.date;
          return (
            <button
              key={key}
              onClick={() => onSelect(g)}
              style={{
                padding: '5px 12px',
                border: isSelected
                  ? '1px solid var(--accent-mint)'
                  : '1px solid var(--border-dim)',
                borderRadius: 4,
                background: isSelected ? 'rgba(0,229,160,0.08)' : 'var(--bg-base)',
                cursor: 'pointer',
                display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2,
              }}
            >
              <div style={{
                fontSize: 12, fontWeight: 700,
                color: isSelected ? 'var(--accent-mint)' : 'var(--text-primary)',
                fontVariantNumeric: 'tabular-nums',
              }}>
                {g.away_abbr} @ {g.home_abbr}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', display: 'flex', gap: 6 }}>
                <span style={{
                  color: g.label === 'Today' ? 'var(--accent-amber)' : 'var(--accent-cyan)',
                }}>{g.label}</span>
                <span>{new Date(g.game_time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })}</span>
              </div>
            </button>
          );
        })}

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          {selected && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              {selected.away_abbr} @ {selected.home_abbr} · {selected.label}
            </span>
          )}
          <button
            className="btn-ghost"
            onClick={onScan}
            disabled={scanning || !selected}
            style={{
              fontSize: 10, padding: '4px 14px',
              color: scanning ? 'var(--accent-amber)' : selected ? 'var(--accent-mint)' : 'var(--text-dim)',
              borderColor: scanning ? 'rgba(245,166,35,0.3)' : selected ? 'rgba(0,229,160,0.3)' : 'var(--border-dim)',
              display: 'flex', alignItems: 'center', gap: 5,
            }}
          >
            {scanning ? (
              <>
                <span style={{ fontSize: 12, animation: 'spin 1s linear infinite' }}>⟳</span>
                Scanning...
              </>
            ) : (
              <>
                <span style={{ fontSize: 12 }}>▶</span>
                Run Scan
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function EVSignalArbCard({ signal }: { signal: Record<string, unknown> }) {
  const [stake, setStake] = useState(100);
  const direction = (signal.direction as string) || 'over';
  const isUnder = direction === 'under';
  const evPct = (signal.ev_pct as number) * 100;
  const truePct = (signal.true_prob as number) * 100;
  const impliedPct = (signal.implied_prob as number) * 100;
  const probGap = truePct - impliedPct;
  const estimatedProfit = (signal.ev_pct as number) * stake;
  const dirLabel = isUnder ? 'U' : 'O';
  const dirColor = isUnder ? 'var(--accent-amber)' : 'var(--accent-mint)';

  return (
    <div className="card ev-card ev-alert" style={{ marginBottom: 10 }}>
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--border-dim)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="live-dot" style={{ width: 8, height: 8, background: dirColor }} />
          <div>
            <span style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: 13 }}>
              {signal.player as string}
            </span>
            <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 8 }}>
              {(signal.prop_type as string).replace(/_/g, ' ').toUpperCase()}
            </span>
            {/* Direction badge — explicit OVER/UNDER so there's no ambiguity */}
            <span style={{
              marginLeft: 6,
              padding: '1px 6px',
              borderRadius: 3,
              fontSize: 11,
              fontWeight: 700,
              background: isUnder ? 'rgba(245,166,35,0.15)' : 'rgba(0,229,160,0.12)',
              color: dirColor,
              border: `1px solid ${isUnder ? 'rgba(245,166,35,0.35)' : 'rgba(0,229,160,0.3)'}`,
            }}>
              {dirLabel} {signal.line as number}
            </span>
          </div>
          <span className="badge badge-blue">NBA</span>
          {(signal.pp_odds_tier as string) === 'demon' && (
            <span className="badge badge-amber">DEMON</span>
          )}
          {(signal.gated as boolean) && (
            <span className="badge badge-amber">GATED</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 2 }}>EDGE (pp)</div>
            <div style={{ color: dirColor, fontWeight: 700, fontSize: 16 }}>
              +{evPct.toFixed(1)}%
            </div>
          </div>
        </div>
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1px 1fr 1px 1fr',
        padding: '12px 14px', gap: 0,
      }}>
        <ProbSide
          label={isUnder ? 'MODEL PROB (UNDER)' : 'MODEL PROB (OVER)'}
          value={fmt_pct(signal.true_prob as number)}
          color="var(--accent-cyan)"
          note="PostgreSQL base"
        />
        <div className="divider-v" />
        <ProbSide label="BOOK IMPLIED" value={fmt_pct(signal.implied_prob as number)} color="var(--text-secondary)" note={`${signal.sportsbook as string} ${fmt_odds(signal.american_odds as number)}`} />
        <div className="divider-v" />
        <ProbSide
          label="PROB GAP"
          value={`+${probGap.toFixed(1)}pp`}
          color={probGap >= 10 ? dirColor : 'var(--accent-amber)'}
          note={`n=${(signal.sample_size as number) ?? '—'} · μ=${((signal.mean_stat as number))?.toFixed(1) ?? '—'}`}
        />
      </div>

      <div style={{
        padding: '8px 14px',
        borderTop: '1px solid var(--border-dim)',
        background: isUnder ? 'rgba(245,166,35,0.02)' : 'rgba(0,229,160,0.02)',
      }}>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 5 }}>
          ESTIMATE DETAILS
        </div>
        <p>Estimated win probability: {fmt_pct(signal.true_prob as number)}. Probability edge: {probGap.toFixed(1)}pp.</p>
        <p>Expected return per unit stake: {signal.expected_return == null ? 'Unavailable' : fmt_pct(signal.expected_return as number)}.</p>
        <p>Sample: {String(signal.sample_size ?? 'unknown')}. Source: {String(signal.data_source ?? 'unknown')}. {signal.gated ? `Gated: ${signal.gate_reason}` : 'Not validated by settled results.'}</p>
      </div>

      {/* Structured matchup context: rest, home/away, opponent def rating, team/opponent */}
      {Boolean(signal.rest_days != null || signal.is_home != null || signal.opponent_def_rating != null || signal.team || signal.opponent) && (
        <div style={{
          padding: '8px 14px',
          borderTop: '1px solid var(--border-dim)',
          background: 'rgba(255,255,255,0.01)',
        }}>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 6 }}>
            MATCHUP CONTEXT
          </div>
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            {Boolean(signal.team || signal.opponent) && (
              <CtxChip
                label="MATCHUP"
                value={signal.team && signal.opponent ? `${signal.team as string} vs ${signal.opponent as string}` : ((signal.team || signal.opponent) as string)}
                color="var(--text-secondary)"
              />
            )}
            {signal.is_home != null && (
              <CtxChip
                label="VENUE"
                value={(signal.is_home as boolean) ? 'HOME' : 'AWAY'}
                color={(signal.is_home as boolean) ? 'var(--accent-mint)' : 'var(--accent-amber)'}
              />
            )}
            {signal.rest_days != null && (
              <CtxChip
                label="REST"
                value={(signal.rest_days as number) === 0 ? 'B2B' : `${signal.rest_days as number}d`}
                color={(signal.rest_days as number) === 0 ? 'var(--accent-amber)' : 'var(--accent-cyan)'}
              />
            )}
            {signal.opponent_def_rating != null && (
              <CtxChip
                label="OPP DEF RTG"
                value={(signal.opponent_def_rating as number).toFixed(1)}
                color={(signal.opponent_def_rating as number) < 110 ? 'var(--accent-amber)' : 'var(--accent-mint)'}
                note={(signal.opponent_def_rating as number) < 110 ? 'strong D' : 'weak D'}
              />
            )}
            {signal.sample_size != null && (
              <CtxChip
                label="SAMPLE"
                value={`${signal.sample_size as number} games`}
                color="var(--text-muted)"
              />
            )}
          </div>
        </div>
      )}

      {/* Trade plan (context-aware bullets from backend) */}
      {Array.isArray(signal.trade_plan) && (signal.trade_plan as string[]).length > 0 && (
        <div style={{
          padding: '8px 14px',
          borderTop: '1px solid var(--border-dim)',
          background: 'rgba(100,200,255,0.02)',
        }}>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 5 }}>
            TRADE PLAN · CONTEXT-ADJUSTED
          </div>
          {(signal.trade_plan as string[]).map((bullet, i) => (
            <div key={i} style={{
              display: 'flex', gap: 6, marginBottom: 3, alignItems: 'flex-start',
            }}>
              <span style={{ color: 'var(--accent-mint)', fontSize: 10, flexShrink: 0 }}>→</span>
              <span style={{ fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{bullet}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{
        padding: '8px 14px 12px', borderTop: '1px solid var(--border-dim)',
        display: 'flex', alignItems: 'center', gap: 12,
        background: 'rgba(0,229,160,0.03)',
      }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>STAKE</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>$</span>
          <input
            type="number" className="term-input" style={{ width: 80 }}
            value={stake} onChange={e => setStake(Number(e.target.value))}
          />
        </div>
        <div className="divider-v" style={{ margin: '0 4px' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>EXPECTED PROFIT</span>
          <span style={{ color: 'var(--accent-mint)', fontWeight: 700, fontSize: 14 }}>
            ${estimatedProfit.toFixed(2)}
          </span>
        </div>
        {!(signal.gated as boolean) && (signal.kelly_fraction as number) > 0 && (
          <>
            <div className="divider-v" style={{ margin: '0 4px' }} />
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              Kelly: <span style={{ color: 'var(--accent-cyan)' }}>
                {((signal.kelly_fraction as number) * 100).toFixed(1)}%
              </span>
            </span>
          </>
        )}
        <div style={{ flex: 1 }} />
        {!!(signal.snapped_at) && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            Snapped {time_ago(signal.snapped_at as string)}
          </span>
        )}
      </div>
    </div>
  );
}

function ProbSide({ label, value, color, note }: { label: string; value: string; color: string; note: string }) {
  return (
    <div style={{ padding: '0 12px', textAlign: 'center' }}>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      <div style={{ marginTop: 5, fontSize: 9, color: 'var(--text-muted)' }}>{note}</div>
    </div>
  );
}

function CtxChip({ label, value, color, note }: { label: string; value: string; color: string; note?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 8, color: 'var(--text-muted)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>
        {value}
        {note && <span style={{ fontSize: 9, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 4 }}>({note})</span>}
      </span>
    </div>
  );
}

export default function Arbitrage() {
  const [sortBy, setSortBy] = useState<'arb' | 'time'>('arb');
  const [evSignals, setEvSignals] = useState<Record<string, unknown>[]>([]);
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());
  const [refreshing, setRefreshing] = useState(false);
  const [games, setGames] = useState<NBAGame[]>([]);
  const [selectedGame, setSelectedGame] = useState<NBAGame | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanMsg, setScanMsg] = useState('');
  const [cacheGame, setCacheGame] = useState<{ home_team: string; away_team: string } | null>(null);
  const [scanNote, setScanNote] = useState<string | null>(null);
  const [scanProgress, setScanProgress] = useState<{
    stage: number; stage_label: string; total_stages: number;
    players_total: number; players_done: number; current_player: string;
  } | null>(null);

  const fetchEVSignals = useCallback(async () => {
    try {
      const res = await fetch('/api/signals', { cache: 'no-store' });
      if (!res.ok) return;
      const json = await res.json();
      // Always update signals (including empty array) — never fall back to stale state
      const filtered = ((json.signals ?? []) as Record<string, unknown>[]).filter(
        s => !s.gated
      );
      setEvSignals(filtered);
      if (json.game) {
        setCacheGame(json.game);
      }
      setScanNote(json.scan_note ?? null);
    } catch {
      // fall through — keep whatever was loaded
    }
  }, []);

  const fetchGames = useCallback(async () => {
    try {
      const res = await fetch('/api/games', { cache: 'no-store' });
      const json = await res.json();
      if (json.games?.length) {
        setGames(json.games);
      }
    } catch { /* ESPN unavailable */ }
  }, []);

  useEffect(() => {
    fetchEVSignals();
    fetchGames();
  }, [fetchEVSignals, fetchGames]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([fetchEVSignals(), fetchGames()]);
    setLastRefreshed(new Date());
    setRefreshing(false);
  };

  const handleScan = async () => {
    if (!selectedGame || scanning) return;
    setScanning(true);
    setScanMsg('');
    setScanProgress(null);
    // Clear stale signals immediately so the old game's data isn't shown during scan
    setEvSignals([]);
    setCacheGame(null);
    try {
      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          team_a: selectedGame.away_abbr,
          team_b: selectedGame.home_abbr,
          date: selectedGame.date,
        }),
      });
      const json = await res.json();
      if (json.status === 'already_running') {
        setScanMsg('Scan already in progress — check back shortly.');
        setScanning(false);
        return;
      }
      setScanMsg(`Scanning ${selectedGame.away_abbr} @ ${selectedGame.home_abbr}…`);
      // Poll for scan completion + progress every 3s, max 40 attempts (~2 min)
      let pollAttempts = 0;
      const poll = setInterval(async () => {
        pollAttempts++;
        try {
          const s = await fetch('/api/scan', { cache: 'no-store' }).then(r => r.json()).catch(() => ({ scanning: true, progress: null }));
          if (s.progress) setScanProgress(s.progress);
          if (!s.scanning) {
            clearInterval(poll);
            setScanning(false);
            setScanMsg('');
            setScanProgress(null);
            await fetchEVSignals();
            setLastRefreshed(new Date());
            return;
          }
        } catch { /* keep polling */ }
        if (pollAttempts >= 40) {
          clearInterval(poll);
          setScanning(false);
          setScanProgress(null);
          setScanMsg('Scan timed out — check scan_out.txt for errors.');
        }
      }, 3000);
    } catch {
      setScanMsg('Scan request failed — check server logs.');
      setScanning(false);
      setScanProgress(null);
    }
  };

  const evSorted = [...evSignals].sort((a, b) =>
    sortBy === 'arb'
      ? (b.ev_pct as number) - (a.ev_pct as number)
      : new Date(b.snapped_at as string).getTime() - new Date(a.snapped_at as string).getTime()
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--border-dim)',
        background: 'var(--bg-base)',
        display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
      }}>
        <div className="section-header">EV Alerts</div>
        {evSorted.length > 0 && (
          <>
            <span className="live-dot live-dot-amber" style={{ width: 8, height: 8 }} />
            <span style={{ color: 'var(--accent-amber)', fontSize: 10, fontWeight: 600 }}>
              {evSorted.length} SIGNALS
            </span>
          </>
        )}
        {cacheGame && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            — {cacheGame.away_team} @ {cacheGame.home_team}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>
          {time_ago(lastRefreshed.toISOString())}
        </span>
        <button
          className="btn-ghost"
          onClick={handleRefresh}
          disabled={refreshing}
          style={{
            fontSize: 10, padding: '3px 12px',
            color: refreshing ? 'var(--accent-amber)' : 'var(--accent-mint)',
            borderColor: refreshing ? 'rgba(245,166,35,0.3)' : 'rgba(0,229,160,0.3)',
            display: 'flex', alignItems: 'center', gap: 5,
          }}
        >
          <span style={{ fontSize: 12 }}>↻</span>
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
        <div className="divider-v" style={{ margin: '0 4px' }} />
        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>Sort:</span>
        <button className="btn-ghost" onClick={() => setSortBy('arb')} style={{ fontSize: 10, padding: '3px 10px', color: sortBy === 'arb' ? 'var(--accent-mint)' : undefined }}>By edge</button>
        <button className="btn-ghost" onClick={() => setSortBy('time')} style={{ fontSize: 10, padding: '3px 10px', color: sortBy === 'time' ? 'var(--accent-mint)' : undefined }}>By Time</button>
      </div>

      {/* Info banner */}
      <div style={{
        background: 'rgba(155,109,255,0.06)', borderBottom: '1px solid rgba(155,109,255,0.15)',
        padding: '7px 14px', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
      }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent-purple)" strokeWidth="2">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span style={{ fontSize: 10, color: 'var(--accent-purple)' }}>
          Only eligible signals are shown. Edge is a probability difference in percentage points; expected return uses the quoted payout.

        </span>
      </div>

      {/* Game selector */}
      <div style={{ flexShrink: 0 }}>
        <GameSelector
          games={games}
          selected={selectedGame}
          onSelect={setSelectedGame}
          scanning={scanning}
          onScan={handleScan}
        />
        {(scanning || scanMsg) && (
          <div style={{
            padding: '8px 14px',
            background: scanning ? 'rgba(245,166,35,0.04)' : 'rgba(0,229,160,0.04)',
            borderBottom: '1px solid var(--border-dim)',
          }}>
            {/* Status line */}
            <div style={{
              fontSize: 10,
              color: scanning ? 'var(--accent-amber)' : 'var(--accent-mint)',
              marginBottom: scanning && scanProgress ? 6 : 0,
            }}>
              {scanMsg || (scanning ? 'Starting scan...' : '')}
              {scanning && scanProgress && (
                <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                  {scanProgress.stage_label}
                </span>
              )}
            </div>
            {/* Progress bar */}
            {scanning && (() => {
              const p = scanProgress;
              let pct = 0;
              if (p) {
                if (p.stage <= 1) pct = 5;
                else if (p.stage === 2) pct = 20;
                else if (p.stage === 3) pct = 35;
                else if (p.stage === 4) {
                  const base = 40;
                  const range = 58;
                  pct = p.players_total > 0
                    ? base + Math.round((p.players_done / p.players_total) * range)
                    : base;
                }
              }
              return (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    flex: 1, height: 3, borderRadius: 2,
                    background: 'rgba(255,255,255,0.06)', overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${pct}%`,
                      height: '100%',
                      background: 'var(--accent-amber)',
                      borderRadius: 2,
                      transition: 'width 0.6s ease',
                    }} />
                  </div>
                  <span style={{ fontSize: 9, color: 'var(--text-dim)', minWidth: 28, textAlign: 'right' }}>
                    {pct}%
                  </span>
                  {p && p.players_total > 0 && (
                    <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>
                      {p.players_done}/{p.players_total} players
                    </span>
                  )}
                </div>
              );
            })()}
          </div>
        )}
      </div>

      {/* EV signal cards */}
      <div style={{ flex: 1, overflow: 'auto', padding: '14px' }}>
        {evSorted.length > 0 ? (
          <>
            <div style={{
              fontSize: 9, color: 'var(--text-muted)',
              letterSpacing: '0.12em', marginBottom: 8, textTransform: 'uppercase',
            }}>
              Single-Book EV Signals — Pipeline ({evSorted.length})
            </div>
            {evSorted.map((s, i) => (
              <EVSignalArbCard key={(s.id as string) || i} signal={s} />
            ))}
          </>
        ) : (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', height: '60%', gap: 12,
          }}>
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--text-dim)" strokeWidth="1.5">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
            </svg>
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              {scanNote ? 'Scan complete — no signals' : 'No EV signals loaded'}
            </span>
            <span style={{ color: 'var(--text-dim)', fontSize: 10, textAlign: 'center', maxWidth: 400 }}>
              {scanNote
                ? scanNote
                : 'Select a game above and click Run Scan to analyze props against the historical distribution model.'}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
