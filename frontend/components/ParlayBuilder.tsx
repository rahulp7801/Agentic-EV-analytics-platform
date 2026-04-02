'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';

// PrizePicks Power Play payouts (all legs must hit)
const PP_PAYOUTS: Record<number, number> = { 2: 3, 3: 5, 4: 10, 5: 20 };
const GOBLIN_PRICE = -110;

function fmt_pct(n: number) { return (n * 100).toFixed(1) + '%'; }
function fmt_odds(n: number) { return n > 0 ? '+' + n : String(n); }

interface Signal {
  id: string;
  player: string;
  team: string;
  opponent: string;
  game_id?: string;
  prop_type: string;
  line: number;
  direction: string;
  true_prob: number;
  implied_prob: number;
  ev_pct: number;
  kelly_fraction: number;
  american_odds: number;
  pp_odds_tier?: string;
  sportsbook: string;
  gated?: boolean;
  sample_size?: number;
  mean_stat?: number;
  strength?: string;
  trade_plan?: string[];
  opponent_def_rating?: number;
  rest_days?: number;
  is_home?: boolean;
  home_team?: string;
  away_team?: string;
}

interface ParlayLeg {
  signal: Signal;
}

interface ParlayCombo {
  legs: ParlayLeg[];
  joint_prob: number;
  payout: number;
  ev_pct: number;
  kelly_fraction: number;
  implied_prob: number;
}

/** Fractional Kelly for a parlay bet. */
function parlay_kelly(joint_prob: number, payout: number): number {
  const b = payout - 1;          // net winnings per unit
  const p = joint_prob;
  const q = 1 - p;
  const f_star = (b * p - q) / b; // full Kelly
  if (f_star <= 0) return 0;
  return Math.min(f_star * 0.25, 0.25); // 25% fractional cap
}

/**
 * Find optimal n-leg combo maximizing joint true_prob (= maximizing EV since
 * payout is fixed per n).
 * Constraint: max 1 prop per player (correlation guard).
 */
function findOptimalCombo(signals: Signal[], n: number): ParlayCombo | null {
  const payout = PP_PAYOUTS[n];
  if (!payout || signals.length < n) return null;

  let best: Signal[] | null = null;
  let bestEV = -Infinity;

  function recurse(start: number, chosen: Signal[], usedPlayers: Set<string>): void {
    if (chosen.length === n) {
      const joint = chosen.reduce((p, s) => p * s.true_prob, 1);
      const ev = joint * payout - 1;
      if (ev > bestEV) {
        bestEV = ev;
        best = [...chosen];
      }
      return;
    }
    const remaining = n - chosen.length;
    if (signals.length - start < remaining) return; // prune
    for (let i = start; i < signals.length; i++) {
      const s = signals[i];
      if (usedPlayers.has(s.player)) continue;
      usedPlayers.add(s.player);
      chosen.push(s);
      recurse(i + 1, chosen, usedPlayers);
      chosen.pop();
      usedPlayers.delete(s.player);
    }
  }

  recurse(0, [], new Set());
  if (!best) return null;

  const joint = (best as Signal[]).reduce((p, s) => p * s.true_prob, 1);
  const ev = joint * payout - 1;
  const kelly = parlay_kelly(joint, payout);

  return {
    legs: (best as Signal[]).map(s => ({ signal: s })),
    joint_prob: joint,
    payout,
    ev_pct: ev,
    kelly_fraction: kelly,
    implied_prob: 1 / payout,
  };
}

function computeCustomCombo(selected: Signal[]): ParlayCombo | null {
  const n = selected.length;
  const payout = PP_PAYOUTS[n];
  if (!payout || n < 2) return null;
  const joint = selected.reduce((p, s) => p * s.true_prob, 1);
  const ev = joint * payout - 1;
  return {
    legs: selected.map(s => ({ signal: s })),
    joint_prob: joint,
    payout,
    ev_pct: ev,
    kelly_fraction: parlay_kelly(joint, payout),
    implied_prob: 1 / payout,
  };
}

function ParlayLegRow({ leg, index }: { leg: ParlayLeg; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const s = leg.signal;
  const hasPlan = Array.isArray(s.trade_plan) && s.trade_plan.length > 0;

  return (
    <div style={{
      background: 'rgba(255,255,255,0.02)',
      borderRadius: 3,
      border: '1px solid var(--border-dim)',
      marginBottom: 4,
      overflow: 'hidden',
    }}>
      {/* Leg summary row */}
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '5px 8px',
          cursor: hasPlan ? 'pointer' : 'default',
        }}
        onClick={() => hasPlan && setExpanded(x => !x)}
      >
        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', minWidth: 14 }}>
          {index + 1}.
        </span>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
          {s.player}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          {s.prop_type.replace(/_/g, ' ').toUpperCase()} O{s.line}
        </span>
        {s.away_team && s.home_team && (
          <span style={{ fontSize: 8, color: 'var(--text-dim)' }}>
            {s.away_team}@{s.home_team}
          </span>
        )}
        {/* Inline context badges */}
        {s.rest_days === 0 && (
          <span style={{ fontSize: 9, color: 'var(--accent-red)', background: 'rgba(255,80,80,0.12)', padding: '1px 5px', borderRadius: 3 }}>B2B</span>
        )}
        {s.opponent_def_rating != null && s.opponent_def_rating > 116 && (
          <span style={{ fontSize: 9, color: 'var(--accent-mint)', background: 'rgba(0,229,160,0.1)', padding: '1px 5px', borderRadius: 3 }}>WEAK D</span>
        )}
        {s.is_home && (
          <span style={{ fontSize: 9, color: 'var(--accent-cyan)', background: 'rgba(0,180,255,0.1)', padding: '1px 5px', borderRadius: 3 }}>HOME</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--accent-cyan)', fontVariantNumeric: 'tabular-nums' }}>
          {fmt_pct(s.true_prob)} model
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>
          {fmt_odds(s.american_odds)}
        </span>
        {s.pp_odds_tier === 'demon' && (
          <span className="badge badge-amber" style={{ fontSize: 8 }}>DEMON</span>
        )}
        {hasPlan && (
          <span style={{ fontSize: 9, color: 'var(--text-dim)', marginLeft: 4 }}>{expanded ? '▲' : '▼'}</span>
        )}
      </div>

      {/* Expandable trade plan */}
      {expanded && hasPlan && (
        <div style={{
          padding: '6px 8px 8px 28px',
          borderTop: '1px solid var(--border-dim)',
          background: 'rgba(0,229,160,0.02)',
        }}>
          {(s.trade_plan as string[]).map((bullet, bi) => (
            <div key={bi} style={{ display: 'flex', gap: 5, marginBottom: 3, alignItems: 'flex-start' }}>
              <span style={{ color: 'var(--accent-mint)', fontSize: 9, flexShrink: 0, marginTop: 2 }}>→</span>
              <span style={{ fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{bullet}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ParlayCard({
  combo,
  label,
  isCustom,
}: {
  combo: ParlayCombo;
  label: string;
  isCustom?: boolean;
}) {
  const [stake, setStake] = useState(100);
  const netProfit = combo.ev_pct > 0 ? combo.ev_pct * stake : 0;
  const isPositiveEV = combo.ev_pct > 0;

  return (
    <div className="card ev-card" style={{
      marginBottom: 12,
      border: `1px solid ${isPositiveEV ? 'rgba(0,229,160,0.25)' : 'rgba(255,80,80,0.2)'}`,
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px',
        borderBottom: '1px solid var(--border-dim)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span className={`badge ${isPositiveEV ? 'badge-blue' : ''}`} style={{
          background: isPositiveEV ? undefined : 'rgba(255,80,80,0.12)',
          color: isPositiveEV ? undefined : 'var(--accent-red)',
        }}>
          {label}
        </span>
        {isCustom && <span className="badge badge-amber">CUSTOM</span>}
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {combo.legs.length}-Pick Power Play
        </span>
        <span style={{
          marginLeft: 4, fontSize: 11, fontWeight: 700,
          color: 'var(--accent-cyan)',
        }}>
          {combo.payout}x payout
        </span>
        <div style={{ flex: 1 }} />
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 2 }}>PARLAY EV</div>
          <div style={{
            fontWeight: 700, fontSize: 16,
            color: isPositiveEV ? 'var(--accent-mint)' : 'var(--accent-red)',
          }}>
            {isPositiveEV ? '+' : ''}{(combo.ev_pct * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      {/* Prob breakdown */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1px 1fr 1px 1fr',
        padding: '10px 14px',
      }}>
        <ProbCell label="JOINT PROB" value={fmt_pct(combo.joint_prob)} color="var(--accent-cyan)" />
        <div className="divider-v" />
        <ProbCell label="BREAKEVEN" value={fmt_pct(combo.implied_prob)} color="var(--text-secondary)" />
        <div className="divider-v" />
        <ProbCell
          label="KELLY STAKE"
          value={combo.kelly_fraction > 0 ? fmt_pct(combo.kelly_fraction) : 'N/A'}
          color={combo.kelly_fraction > 0 ? 'var(--accent-mint)' : 'var(--text-dim)'}
        />
      </div>

      {/* Legs */}
      <div style={{
        padding: '8px 14px',
        borderTop: '1px solid var(--border-dim)',
        display: 'flex', flexDirection: 'column', gap: 4,
      }}>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 4 }}>
          LEGS · CORRELATION GUARD ACTIVE
        </div>
        {combo.legs.map((leg, i) => (
          <ParlayLegRow key={leg.signal.id + i} leg={leg} index={i} />
        ))}
      </div>

      {/* Mispricing logic */}
      <div style={{
        padding: '6px 14px',
        borderTop: '1px solid var(--border-dim)',
        background: 'rgba(0,229,160,0.02)',
      }}>
        <span style={{ fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          Joint probability {fmt_pct(combo.joint_prob)} vs PrizePicks breakeven {fmt_pct(combo.implied_prob)} ({combo.payout}x).{' '}
          {isPositiveEV
            ? `Edge of +${((combo.joint_prob - combo.implied_prob) * 100).toFixed(1)}pp — model estimates this parlay hits more often than the payout requires.`
            : `Model probability falls below breakeven — avoid this parlay.`}
        </span>
      </div>

      {/* Stake calculator */}
      {isPositiveEV && (
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
          <div style={{ display: 'flex', gap: 16 }}>
            <div>
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>IF HIT </span>
              <span style={{ color: 'var(--accent-mint)', fontWeight: 700, fontSize: 13 }}>
                ${(stake * combo.payout).toFixed(2)}
              </span>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>EXP PROFIT </span>
              <span style={{ color: 'var(--accent-cyan)', fontWeight: 700, fontSize: 13 }}>
                ${netProfit.toFixed(2)}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ProbCell({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ padding: '0 10px', textAlign: 'center' }}>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  );
}

export default function ParlayBuilder({
  externalLegs = [],
  onRemoveExternal,
}: {
  externalLegs?: Signal[];
  onRemoveExternal?: (id: string) => void;
}) {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [cacheGames, setCacheGames] = useState<{ home_team: string; away_team: string; game_id?: string }[]>([]);
  const [activeTab, setActiveTab] = useState<'optimal' | 'custom'>('optimal');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [teamFilter, setTeamFilter] = useState<string>('ALL');

  const fetchSignals = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/signals', { cache: 'no-store' });
      if (!res.ok) { setLoading(false); return; }
      const json = await res.json();
      const eligible: Signal[] = ((json.signals || []) as Signal[]).filter(
        s => s.ev_pct > 0 && !s.gated && s.american_odds !== GOBLIN_PRICE
      );
      setSignals(eligible);
      // Support both new multi-game format (games[]) and legacy single-game format (game{})
      if (json.games && json.games.length > 0) {
        setCacheGames(json.games);
      } else if (json.game) {
        setCacheGames([json.game]);
      }
    } catch { /* unavailable */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchSignals(); }, [fetchSignals]);

  // Merge external legs (added from EV Dashboard) into eligible signals
  const allSignals = [
    ...signals,
    ...externalLegs.filter(e => !signals.some(s => s.id === e.id)),
  ];

  const optimalCombos = useMemo(() => {
    return [2, 3, 4, 5]
      .map(n => ({ n, combo: findOptimalCombo(allSignals, n) }))
      .filter(x => x.combo !== null && x.combo.ev_pct > 0) as { n: number; combo: ParlayCombo }[];
  }, [allSignals]);

  // All unique teams across loaded signals
  const allTeams = useMemo(() => {
    const teams = new Set<string>();
    allSignals.forEach(s => { if (s.team) teams.add(s.team); });
    return Array.from(teams).sort();
  }, [allSignals]);

  // Signals filtered by team picker (for custom mode selection list)
  const filteredSignals = useMemo(
    () => teamFilter === 'ALL' ? allSignals : allSignals.filter(s => s.team === teamFilter),
    [allSignals, teamFilter]
  );

  const customSelected = useMemo(
    () => allSignals.filter(s => selectedIds.has(s.id)),
    [allSignals, selectedIds]
  );

  const customCombo = useMemo(
    () => computeCustomCombo(customSelected),
    [customSelected]
  );

  // Warn about player duplication in custom mode
  const playerCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    customSelected.forEach(s => { counts[s.player] = (counts[s.player] || 0) + 1; });
    return counts;
  }, [customSelected]);

  const hasDuplicatePlayers = Object.values(playerCounts).some(v => v > 1);

  const toggleLeg = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const tabStyle = (active: boolean) => ({
    padding: '4px 14px',
    fontSize: 10,
    fontWeight: active ? 700 : 400,
    color: active ? 'var(--accent-mint)' : 'var(--text-muted)',
    borderBottom: active ? '2px solid var(--accent-mint)' : '2px solid transparent',
    background: 'none', border: 'none', cursor: 'pointer',
    borderRadius: 0,
    // override border-bottom separately
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--border-dim)',
        background: 'var(--bg-base)',
        display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
      }}>
        <div className="section-header">Optimal Parlay Builder</div>
        {cacheGames.length > 0 && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            — {cacheGames.map(g => `${g.away_team} @ ${g.home_team}`).join(' · ')}
          </span>
        )}
        {allSignals.length > 0 && (
          <span className="badge badge-blue">{allSignals.length} eligible legs</span>
        )}
        {externalLegs.length > 0 && (
          <span className="badge badge-mint" style={{ fontSize: 9 }}>{externalLegs.length} from EV Dashboard</span>
        )}
        <div style={{ flex: 1 }} />
        <button
          className="btn-ghost"
          onClick={fetchSignals}
          style={{ fontSize: 10, padding: '3px 12px', color: 'var(--accent-mint)', borderColor: 'rgba(0,229,160,0.3)', display: 'flex', alignItems: 'center', gap: 5 }}
        >
          <span style={{ fontSize: 12 }}>↻</span> Refresh
        </button>
      </div>

      {/* Info banner */}
      <div style={{
        background: 'rgba(0,180,255,0.05)', borderBottom: '1px solid rgba(0,180,255,0.15)',
        padding: '7px 14px', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
      }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="2">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span style={{ fontSize: 10, color: 'var(--accent-cyan)' }}>
          PrizePicks Power Play · Payouts: 2-pick 3x · 3-pick 5x · 4-pick 10x · 5-pick 20x.
          Goblin (-110) lines excluded. Max 1 prop per player per combo (correlation guard).
          {cacheGames.length > 1 && ` · ${cacheGames.length} games loaded — mix players across games.`}
        </span>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex', borderBottom: '1px solid var(--border-dim)',
        background: 'var(--bg-void)', flexShrink: 0,
      }}>
        <button
          onClick={() => setActiveTab('optimal')}
          style={{ ...tabStyle(activeTab === 'optimal'), borderBottom: activeTab === 'optimal' ? '2px solid var(--accent-mint)' : '2px solid transparent', padding: '8px 16px' }}
        >
          OPTIMAL
        </button>
        <button
          onClick={() => setActiveTab('custom')}
          style={{ ...tabStyle(activeTab === 'custom'), borderBottom: activeTab === 'custom' ? '2px solid var(--accent-mint)' : '2px solid transparent', padding: '8px 16px' }}
        >
          CUSTOM BUILDER
        </button>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '14px' }}>
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 40, color: 'var(--text-muted)', fontSize: 12 }}>
            Loading signals…
          </div>
        ) : allSignals.length === 0 ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', height: '60%', gap: 12,
          }}>
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>No +EV signals available</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 10, textAlign: 'center', maxWidth: 300 }}>
              Run a game scan in the EV Alerts view to load signals, then return here to build optimal parlays.
            </span>
          </div>
        ) : activeTab === 'optimal' ? (
          <>
            {optimalCombos.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 11, padding: '20px 0' }}>
                No +EV parlay combinations found with available signals.
              </div>
            ) : (
              optimalCombos.map(({ n, combo }) => (
                <ParlayCard
                  key={n}
                  combo={combo}
                  label={`OPTIMAL ${n}-PICK`}
                />
              ))
            )}
          </>
        ) : (
          /* Custom builder */
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            {/* Left: leg selector */}
            <div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.12em', marginBottom: 6 }}>
                SELECT LEGS (2–5)
              </div>
              {/* Team filter pills */}
              {allTeams.length > 1 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                  {['ALL', ...allTeams].map(t => (
                    <button
                      key={t}
                      onClick={() => setTeamFilter(t)}
                      style={{
                        fontSize: 9, padding: '2px 8px', borderRadius: 3, cursor: 'pointer',
                        border: `1px solid ${teamFilter === t ? 'var(--accent-cyan)' : 'var(--border-dim)'}`,
                        background: teamFilter === t ? 'rgba(0,180,255,0.12)' : 'transparent',
                        color: teamFilter === t ? 'var(--accent-cyan)' : 'var(--text-muted)',
                      }}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              )}
              {filteredSignals.map(s => {
                const checked = selectedIds.has(s.id);
                const isDupe = checked && (playerCounts[s.player] || 0) > 1;
                const gameLabel = s.away_team && s.home_team ? `${s.away_team}@${s.home_team}` : (s.team || '');
                return (
                  <div
                    key={s.id}
                    onClick={() => toggleLeg(s.id)}
                    style={{
                      padding: '7px 10px',
                      marginBottom: 4,
                      border: `1px solid ${checked ? (isDupe ? 'rgba(255,80,80,0.4)' : 'rgba(0,229,160,0.3)') : 'var(--border-dim)'}`,
                      borderRadius: 4,
                      background: checked ? (isDupe ? 'rgba(255,80,80,0.05)' : 'rgba(0,229,160,0.05)') : 'var(--bg-base)',
                      cursor: 'pointer',
                      display: 'flex', alignItems: 'center', gap: 8,
                    }}
                  >
                    <div style={{
                      width: 14, height: 14, borderRadius: 3,
                      border: `1px solid ${checked ? 'var(--accent-mint)' : 'var(--border-dim)'}`,
                      background: checked ? 'var(--accent-mint)' : 'transparent',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      {checked && <span style={{ color: '#000', fontSize: 10, fontWeight: 900 }}>✓</span>}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ fontWeight: 700, fontSize: 11, color: 'var(--text-primary)' }}>{s.player}</span>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 6 }}>
                        {s.prop_type.replace(/_/g, ' ').toUpperCase()} O{s.line}
                      </span>
                      {gameLabel && (
                        <span style={{ fontSize: 8, color: 'var(--text-dim)', marginLeft: 6 }}>
                          {gameLabel}
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: 10, color: 'var(--accent-cyan)', fontVariantNumeric: 'tabular-nums' }}>
                      {fmt_pct(s.true_prob)}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--accent-mint)', fontWeight: 600 }}>
                      +{(s.ev_pct * 100).toFixed(1)}%
                    </span>
                    {isDupe && (
                      <span style={{ fontSize: 9, color: 'var(--accent-red)' }}>⚠ dupe player</span>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Right: live combo preview */}
            <div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.12em', marginBottom: 8 }}>
                COMBO PREVIEW
              </div>
              {hasDuplicatePlayers && (
                <div style={{
                  padding: '8px 12px', marginBottom: 10,
                  background: 'rgba(255,80,80,0.08)',
                  border: '1px solid rgba(255,80,80,0.25)',
                  borderRadius: 4, fontSize: 10, color: 'var(--accent-red)',
                }}>
                  ⚠ Duplicate player detected — parlays with correlated legs inflate apparent EV.
                  Correlation Guard recommends max 1 prop per player.
                </div>
              )}
              {customSelected.length < 2 ? (
                <div style={{
                  padding: '20px', textAlign: 'center',
                  border: '1px dashed var(--border-dim)', borderRadius: 4,
                  color: 'var(--text-dim)', fontSize: 11,
                }}>
                  Select 2–5 legs to preview the parlay
                </div>
              ) : customSelected.length > 5 ? (
                <div style={{
                  padding: '12px', textAlign: 'center',
                  border: '1px solid rgba(255,80,80,0.3)', borderRadius: 4,
                  color: 'var(--accent-red)', fontSize: 11,
                }}>
                  Max 5 legs for PrizePicks Power Play
                </div>
              ) : customCombo ? (
                <ParlayCard combo={customCombo} label={`${customSelected.length}-PICK`} isCustom />
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
