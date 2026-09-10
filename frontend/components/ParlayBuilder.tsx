"use client";
import { useEffect, useState } from 'react';
import type { EVSignal } from '@/lib/types';
import { parlayScenario, signalMetrics } from '@/lib/signalMetrics';
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
export default function ParlayBuilder({ externalLegs = [], onRemoveExternal }: {
  externalLegs?: EVSignal[]; onRemoveExternal?: (id: string) => void;
}) {
  const [signals, setSignals] = useState<EVSignal[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [payout, setPayout] = useState('');
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    fetch('/api/signals').then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(data => setSignals(data.signals ?? [])).catch(() => setError('Signals unavailable.'));
    const timer = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(timer);
  }, []);
  const candidates = [...new Map([...signals, ...externalLegs].map(s => [s.id, s])).values()]
    .filter(s => !signalMetrics({...s}, now).gated && !(s.push_probability ?? 0));
  const legs = candidates.filter(s => selected.includes(s.id) || externalLegs.some(e => e.id === s.id));
  const scenario = parlayScenario(legs.map(s => s.true_prob), Number(payout));
  return <div style={{padding: 20, overflow: 'auto'}}>
    <h2>Parlay scenario calculator</h2>
    <p>Choose at least two legs and enter the offered total return per unit staked, including your stake.</p>
    <p>The independence estimate assumes the legs do not affect each other. This model has no validated joint forecast; the probability range shows all dependence structures compatible with the individual estimates. Push markets are excluded.</p>
    <label>Offered total return (3 means $3 returned per $1 staked):{' '}
      <input aria-label="Offered total return" type="number" min="1.01" step="0.01" value={payout} onChange={e => setPayout(e.target.value)} />
    </label>
    {error && <p>{error}</p>}
    {!candidates.length && <p>No eligible fresh signals. Run a scan with supported sportsbook prices.</p>}
    <div style={{margin: '16px 0', display: 'grid', gap: 8}}>
      {candidates.map(s => <label key={s.id}>
        <input type="checkbox" checked={legs.some(l => l.id === s.id)} onChange={e => {
          if (!e.target.checked) onRemoveExternal?.(s.id);
          setSelected(ids => e.target.checked ? [...ids, s.id] : ids.filter(id => id !== s.id));
        }} />{' '}{s.player} {s.direction} {s.line} {s.prop_type} ({s.sportsbook}) - estimated {pct(s.true_prob)}
      </label>)}
    </div>
    {scenario && <section style={{border: '1px solid var(--border-dim)', padding: 16}}>
      <p>{legs.length} legs | Independence scenario probability: {pct(scenario.independent)}</p>
      <p>Probability bounds with unknown dependence: {pct(scenario.lower)} to {pct(scenario.upper)}</p>
      <p>Expected return assuming independence: {pct(scenario.expectedReturn)}</p>
      <p>Expected return bounds: {pct(scenario.lower * Number(payout) - 1)} to {pct(scenario.upper * Number(payout) - 1)}</p>
      <p>These are scenarios based on unvalidated individual estimates, not a stake recommendation.</p>
    </section>}
  </div>;
}
