'use client';

import { useEffect, useState } from 'react';
import type { EVSignal, Sport } from '@/lib/types';
import { parlayScenario, signalMetrics } from '@/lib/signalMetrics';
import styles from './ResearchViews.module.css';

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;

export default function ParlayBuilder({ sport, externalLegs = [], onRemoveExternal }: {
  sport: Sport;
  externalLegs?: EVSignal[];
  onRemoveExternal?: (id: string) => void;
}) {
  const [signals, setSignals] = useState<EVSignal[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [payout, setPayout] = useState('');
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/signals?sport=${sport}`, { cache: 'no-store', signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(data => { if (!controller.signal.aborted) { setError(''); setSignals(data.signals ?? []); } })
      .catch(() => { if (!controller.signal.aborted) setError('Signals unavailable.'); });
    const timer = setInterval(() => setNow(Date.now()), 15_000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [sport]);

  const candidates = [...new Map([...signals, ...externalLegs].map(signal => [signal.id, signal])).values()]
    .filter(signal => signal.sport === sport)
    .filter(signal => !signalMetrics({ ...signal }, now).gated && !(signal.push_probability ?? 0));
  const legs = candidates.filter(signal => selected.includes(signal.id) || externalLegs.some(item => item.id === signal.id));
  const scenario = parlayScenario(legs.map(signal => signal.true_prob), Number(payout));

  return (
    <section className={styles.toolView} aria-labelledby="scenario-title">
      <header className={styles.toolHeader}>
        <div>
          <small>Dependence stress test</small>
          <h2 id="scenario-title">Scenario lab</h2>
        </div>
        <p>Combine recorded individual estimates and inspect the full probability range allowed by unknown dependence. This is a bound analysis, not a validated joint forecast.</p>
      </header>

      <div className={styles.scenarioGrid}>
        <section className={`${styles.panel} ${styles.scenarioControls}`}>
          <div className={styles.inputField}>
            <label htmlFor="scenario-payout">Offered total return per $1</label>
            <input id="scenario-payout" aria-label="Offered total return" className="term-input" type="number" min="1.01" step="0.01" value={payout} onChange={event => setPayout(event.target.value)} placeholder="e.g. 3.00" />
            <small>Include the returned stake. Enter 3 when a $1 stake returns $3 total.</small>
          </div>
          {error && <div className={styles.notice} role="alert">{error}</div>}
          {!candidates.length ? (
            <div className={styles.notice}>No eligible fresh signals are available. The lab will populate after supported sportsbook prices produce publishable estimates.</div>
          ) : (
            <div className={styles.candidateList}>
              {candidates.map(signal => (
                <label className={styles.candidate} key={signal.id}>
                  <input type="checkbox" checked={legs.some(leg => leg.id === signal.id)} onChange={event => {
                    if (!event.target.checked) onRemoveExternal?.(signal.id);
                    setSelected(ids => event.target.checked ? [...new Set([...ids, signal.id])] : ids.filter(id => id !== signal.id));
                  }} />
                  <span>{signal.player} · {signal.direction} {signal.line} {signal.prop_type}</span>
                  <small>{signal.sportsbook} · {pct(signal.true_prob)}</small>
                </label>
              ))}
            </div>
          )}
        </section>

        <section className={`${styles.panel} ${styles.scenarioResult}`} aria-live="polite">
          <h3 className={styles.panelHeader}>Dependence envelope</h3>
          {!scenario ? (
            <div className={styles.resultEmpty}>Select at least two eligible legs and enter the offered total return.</div>
          ) : (
            <>
              <div className={styles.scenarioHero}>
                <span>Independence scenario probability · {legs.length} legs</span>
                <strong>{pct(scenario.independent)}</strong>
              </div>
              <div className={styles.scenarioMetrics}>
                <div><span>Probability lower bound</span><strong>{pct(scenario.lower)}</strong></div>
                <div><span>Probability upper bound</span><strong>{pct(scenario.upper)}</strong></div>
                <div><span>Independence expected return</span><strong>{pct(scenario.expectedReturn)}</strong></div>
                <div><span>Expected-return bounds</span><strong>{pct(scenario.lower * Number(payout) - 1)} to {pct(scenario.upper * Number(payout) - 1)}</strong></div>
              </div>
              <p className={styles.scenarioWarning}>These are mathematical scenarios from individual estimates. Unknown correlation can span the displayed bounds, so this result is not a stake recommendation.</p>
            </>
          )}
        </section>
      </div>
    </section>
  );
}
