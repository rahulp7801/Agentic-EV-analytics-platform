'use client';
import { useState, useMemo } from 'react';

function clamp(val: number, min: number, max: number) {
  return Math.min(max, Math.max(min, val));
}

function americanToDecimal(american: number): number {
  if (american > 0) return american / 100;
  return 100 / Math.abs(american);
}

function calcKelly(p: number, b: number, fraction: number): number {
  const q = 1 - p;
  const f = (b * p - q) / b;
  return clamp(f * fraction, 0, 0.25);
}

function calcEV(p: number, b: number): number {
  return p * b - (1 - p);
}

function KellyArcGauge({ fraction }: { fraction: number }) {
  const pct = clamp(fraction / 0.25, 0, 1);
  const R = 52;
  const cx = 70, cy = 65;
  const startAngle = Math.PI;
  const endAngle = 0;
  const angle = startAngle + pct * (endAngle - startAngle + Math.PI); // 180 degrees sweep

  const arcX = (a: number) => cx + R * Math.cos(a);
  const arcY = (a: number) => cy + R * Math.sin(a);

  const path = `M ${arcX(Math.PI)} ${arcY(Math.PI)} A ${R} ${R} 0 0 1 ${arcX(0)} ${arcY(0)}`;

  const needleAngle = Math.PI - pct * Math.PI;
  const nx = cx + (R - 8) * Math.cos(needleAngle);
  const ny = cy + (R - 8) * Math.sin(needleAngle);

  const color = fraction === 0 ? 'var(--text-dim)'
    : fraction >= 0.15 ? 'var(--accent-red)'
    : fraction >= 0.08 ? 'var(--accent-mint)'
    : 'var(--accent-amber)';

  return (
    <svg width={140} height={75} viewBox="0 0 140 75">
      {/* Track */}
      <path d={path} fill="none" stroke="var(--border-dim)" strokeWidth={8} strokeLinecap="round" />
      {/* Fill */}
      {fraction > 0 && (
        <path d={`M ${arcX(Math.PI)} ${arcY(Math.PI)} A ${R} ${R} 0 ${pct > 0.5 ? 1 : 0} 1 ${arcX(needleAngle)} ${arcY(needleAngle)}`}
          fill="none" stroke={color} strokeWidth={8} strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 4px ${color})` }}
        />
      )}
      {/* Needle dot */}
      <circle cx={nx} cy={ny} r={4} fill={color} style={{ filter: `drop-shadow(0 0 3px ${color})` }} />
      {/* Labels */}
      <text x={cx - R - 6} y={cy + 14} fontSize={9} fill="var(--text-muted)" textAnchor="middle">0%</text>
      <text x={cx + R + 6} y={cy + 14} fontSize={9} fill="var(--text-muted)" textAnchor="middle">25%</text>
    </svg>
  );
}

export default function KellyCalc() {
  const [modelProb, setModelProb] = useState(62);
  const [americanOdds, setAmericanOdds] = useState(-110);
  const [fraction, setFraction] = useState(50);
  const [bankroll, setBankroll] = useState(10000);
  const [useCustomImplied, setUseCustomImplied] = useState(false);
  const [customImplied, setCustomImplied] = useState(52.4);

  const results = useMemo(() => {
    const p = modelProb / 100;
    const b = americanToDecimal(americanOdds);
    const frac = fraction / 100;

    const rawKelly = calcKelly(p, b, 1.0);
    const fracKelly = calcKelly(p, b, frac);
    const ev = calcEV(p, b);

    const impliedProb = useCustomImplied
      ? customImplied / 100
      : americanOdds < 0
        ? Math.abs(americanOdds) / (Math.abs(americanOdds) + 100)
        : 100 / (americanOdds + 100);

    const evEdge = p - impliedProb;

    return {
      rawKelly, fracKelly, ev, evEdge, impliedProb,
      stakeAmount: fracKelly * bankroll,
      potentialProfit: fracKelly * bankroll * b,
      potentialLoss: fracKelly * bankroll,
    };
  }, [modelProb, americanOdds, fraction, bankroll, useCustomImplied, customImplied]);

  const kellyPct = results.fracKelly * 100;
  const evPct = results.evEdge * 100;

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: 'var(--bg-base)',
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px',
        borderBottom: '1px solid var(--border-dim)',
        background: 'var(--bg-base)',
        display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
      }}>
        <div className="section-header">Kelly Criterion Sizer</div>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          Fractional Kelly — capped at 25% bankroll per CLAUDE.md prop firm rules
        </span>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 20, display: 'flex', gap: 20, flexWrap: 'wrap', alignContent: 'flex-start' }}>
        {/* Input card */}
        <div className="card" style={{ flex: '1 1 300px', padding: '16px 18px' }}>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 12, color: 'var(--accent-mint)', letterSpacing: '0.12em', marginBottom: 16 }}>
            INPUTS
          </div>

          <InputRow
            label="Model Probability"
            value={modelProb}
            onChange={setModelProb}
            min={1} max={99} step={0.5}
            display={modelProb.toFixed(1) + '%'}
            color="var(--accent-cyan)"
          />
          <InputRow
            label="Bankroll"
            value={bankroll}
            onChange={setBankroll}
            min={100} max={1000000} step={100}
            display={'$' + bankroll.toLocaleString()}
            color="var(--text-primary)"
          />
          <InputRow
            label="Kelly Fraction"
            value={fraction}
            onChange={setFraction}
            min={5} max={100} step={5}
            display={fraction + '%'}
            color="var(--accent-amber)"
          />

          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6, letterSpacing: '0.08em' }}>
              AMERICAN ODDS
            </div>
            <input
              type="number"
              className="term-input"
              value={americanOdds}
              onChange={e => setAmericanOdds(Number(e.target.value))}
              placeholder="-110"
            />
            <div style={{ fontSize: 9, color: 'var(--text-dim)', marginTop: 4 }}>
              Negative = favorite. E.g. -110, +150
            </div>
          </div>

          <div style={{ marginTop: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <input
                type="checkbox"
                checked={useCustomImplied}
                onChange={e => setUseCustomImplied(e.target.checked)}
                style={{ accentColor: 'var(--accent-mint)' }}
              />
              <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
                OVERRIDE IMPLIED PROB
              </span>
            </div>
            {useCustomImplied && (
              <input
                type="number"
                className="term-input"
                value={customImplied}
                onChange={e => setCustomImplied(Number(e.target.value))}
                min={1} max={99} step={0.1}
                placeholder="52.4"
              />
            )}
          </div>
        </div>

        {/* Gauge + output card */}
        <div style={{ flex: '1 1 280px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* Gauge */}
          <div className="card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 12, color: 'var(--accent-mint)', letterSpacing: '0.12em', marginBottom: 10, alignSelf: 'flex-start' }}>
              KELLY GAUGE
            </div>
            <KellyArcGauge fraction={results.fracKelly} />
            <div style={{ textAlign: 'center', marginTop: -8 }}>
              <div style={{
                fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 32,
                color: kellyPct === 0 ? 'var(--text-dim)' : kellyPct >= 15 ? 'var(--accent-red)' : 'var(--accent-mint)',
                lineHeight: 1,
                fontVariantNumeric: 'tabular-nums',
              }}>
                {kellyPct.toFixed(1)}%
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                fractional Kelly ({fraction}% of full Kelly)
              </div>
            </div>
          </div>

          {/* Stake output */}
          <div className="card" style={{ padding: '14px 18px' }}>
            <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 12, color: 'var(--accent-mint)', letterSpacing: '0.12em', marginBottom: 12 }}>
              SIZING OUTPUT
            </div>
            <OutputRow label="Stake Amount" value={'$' + results.stakeAmount.toFixed(2)} color="var(--text-primary)" />
            <OutputRow label="EV Edge" value={(evPct >= 0 ? '+' : '') + evPct.toFixed(2) + '%'}
              color={evPct > 0 ? 'var(--accent-mint)' : 'var(--accent-red)'} />
            <OutputRow label="Expected Profit" value={'$' + (results.stakeAmount * results.ev).toFixed(2)}
              color={results.ev > 0 ? 'var(--accent-mint)' : 'var(--accent-red)'} />
            <OutputRow label="Potential Win" value={'$' + results.potentialProfit.toFixed(2)} color="var(--accent-cyan)" />
            <OutputRow label="Potential Loss" value={'-$' + results.potentialLoss.toFixed(2)} color="var(--accent-red)" />
            <OutputRow label="Implied Prob" value={(results.impliedProb * 100).toFixed(1) + '%'} color="var(--text-secondary)" />
            <OutputRow label="Full Kelly (raw)" value={(results.rawKelly * 100).toFixed(1) + '%'} color="var(--text-muted)" />
          </div>

          {/* Warning */}
          {results.fracKelly === 0 && (
            <div style={{
              padding: '10px 14px',
              background: 'rgba(240,61,61,0.08)',
              border: '1px solid rgba(240,61,61,0.2)',
              borderRadius: 3,
              fontSize: 11,
              color: 'var(--accent-red)',
            }}>
              ⚠ Negative EV — no bet recommended. Adjust inputs or skip this market.
            </div>
          )}
          {results.fracKelly === 0.25 && (
            <div style={{
              padding: '10px 14px',
              background: 'rgba(240,61,61,0.06)',
              border: '1px solid rgba(240,61,61,0.15)',
              borderRadius: 3,
              fontSize: 11,
              color: 'var(--accent-amber)',
            }}>
              ⚠ Hard cap reached (25%). Full Kelly was {(results.rawKelly * 100).toFixed(0)}% — capped per prop firm rules.
            </div>
          )}
        </div>

        {/* Formula reference */}
        <div className="card" style={{ flex: '1 1 260px', padding: '16px 18px' }}>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 12, color: 'var(--accent-mint)', letterSpacing: '0.12em', marginBottom: 14 }}>
            FORMULA REFERENCE
          </div>
          <FormulaBlock
            label="Full Kelly (f*)"
            formula="f* = (b·p - (1-p)) / b"
            note="b = decimal odds, p = win probability"
          />
          <FormulaBlock
            label="Fractional Kelly"
            formula="stake = f* × fraction"
            note={`Using ${fraction}% fraction → ${(results.rawKelly * 100).toFixed(1)}% × ${fraction}% = ${kellyPct.toFixed(1)}%`}
          />
          <FormulaBlock
            label="EV Edge"
            formula="EV = p_model - p_implied"
            note={`${(modelProb).toFixed(1)}% - ${(results.impliedProb * 100).toFixed(1)}% = ${evPct.toFixed(2)}%`}
          />
          <FormulaBlock
            label="Hard Cap Rule"
            formula="max(0, min(0.25, stake))"
            note="CLAUDE.md prop firm: never exceed 25% bankroll"
          />
          <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--bg-surface)', borderRadius: 3, border: '1px solid var(--border-dim)' }}>
            <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.08em', marginBottom: 4 }}>REF: Kelly (1956)</div>
            <div style={{ fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              "A New Interpretation of Information Rate" — Bell System Technical Journal
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InputRow({ label, value, onChange, min, max, step, display, color }: {
  label: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step: number; display: string; color: string;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: '0.08em' }}>{label.toUpperCase()}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color }}>{display}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: 'var(--accent-mint)' }}
      />
    </div>
  );
}

function OutputRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '5px 0', borderBottom: '1px solid var(--border-dim)',
    }}>
      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  );
}

function FormulaBlock({ label, formula, note }: { label: string; formula: string; note: string }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 4 }}>{label.toUpperCase()}</div>
      <div style={{
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 12, color: 'var(--accent-cyan)',
        background: 'var(--bg-surface)',
        padding: '6px 10px', borderRadius: 3,
        border: '1px solid var(--border-dim)',
        marginBottom: 3,
      }}>{formula}</div>
      <div style={{ fontSize: 10, color: 'var(--text-dim)', paddingLeft: 2 }}>{note}</div>
    </div>
  );
}
