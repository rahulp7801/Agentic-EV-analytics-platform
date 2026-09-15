'use client';

import { useMemo, useState } from 'react';
import { calculateKellyScenario } from '@/lib/kellyScenario';
import styles from './ResearchViews.module.css';

function Field({ id, label, value, onChange, placeholder, hint }: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  hint: string;
}) {
  return (
    <div className={styles.inputField}>
      <label htmlFor={id}>{label}</label>
      <input id={id} className="term-input" type="number" value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} />
      <small>{hint}</small>
    </div>
  );
}

function Result({ label, value, note, tone = '' }: { label: string; value: string; note: string; tone?: string }) {
  return (
    <div className={`${styles.resultCell} ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

export default function KellyCalc() {
  const [modelProb, setModelProb] = useState('');
  const [americanOdds, setAmericanOdds] = useState('');
  const [fraction, setFraction] = useState('');
  const [bankroll, setBankroll] = useState('');
  const [useCustomImplied, setUseCustomImplied] = useState(false);
  const [customImplied, setCustomImplied] = useState('');

  const results = useMemo(() => {
    const probability = Number(modelProb) / 100;
    const odds = Number(americanOdds);
    const kellyFraction = Number(fraction) / 100;
    const bankrollValue = Number(bankroll);
    const impliedOverride = Number(customImplied) / 100;
    const hasRequiredInputs = [modelProb, americanOdds, fraction, bankroll].every(value => value.trim() !== '');
    if (!hasRequiredInputs || (useCustomImplied && customImplied.trim() === '')) return null;
    return calculateKellyScenario({
      probability,
      americanOdds: odds,
      kellyFraction,
      bankroll: bankrollValue,
      impliedProbability: useCustomImplied ? impliedOverride : undefined,
    });
  }, [americanOdds, bankroll, customImplied, fraction, modelProb, useCustomImplied]);

  return (
    <section className={styles.toolView} aria-labelledby="kelly-title">
      <header className={styles.toolHeader}>
        <div>
          <small>Manual research tool</small>
          <h2 id="kelly-title">Kelly sizing</h2>
        </div>
        <p>Enter your own probability, price, and bankroll assumptions. Values on this screen are a scenario calculation and are never presented as live recommendations.</p>
      </header>

      <div className={styles.calculatorGrid}>
        <section className={styles.panel}>
          <h3 className={styles.panelHeader}>Scenario inputs</h3>
          <div className={styles.inputGrid}>
            <Field id="kelly-probability" label="Model probability (%)" value={modelProb} onChange={setModelProb} placeholder="e.g. 58" hint="Your probability estimate, between 0 and 100." />
            <Field id="kelly-odds" label="American odds" value={americanOdds} onChange={setAmericanOdds} placeholder="e.g. -110" hint="Use a valid price at or beyond ±100." />
            <Field id="kelly-bankroll" label="Bankroll ($)" value={bankroll} onChange={setBankroll} placeholder="e.g. 1000" hint="Used only to translate the fraction into dollars." />
            <Field id="kelly-fraction" label="Kelly fraction (%)" value={fraction} onChange={setFraction} placeholder="e.g. 25" hint="A fraction of full Kelly, from 0 to 100%." />
            <label className={`${styles.checkboxField} ${styles.inputFieldWide}`}>
              <input type="checkbox" checked={useCustomImplied} onChange={event => setUseCustomImplied(event.target.checked)} />
              Override the price-derived implied probability
            </label>
            {useCustomImplied && (
              <div className={`${styles.inputField} ${styles.inputFieldWide}`}>
                <label htmlFor="kelly-implied">Custom implied probability (%)</label>
                <input id="kelly-implied" className="term-input" type="number" value={customImplied} onChange={event => setCustomImplied(event.target.value)} placeholder="e.g. 52.4" />
                <small>Used for the displayed probability edge; the entered odds still determine payout.</small>
              </div>
            )}
          </div>
        </section>

        <section className={styles.panel} aria-live="polite">
          <h3 className={styles.panelHeader}>Calculated scenario</h3>
          {!results ? (
            <div className={styles.resultEmpty}>Enter four valid assumptions to calculate a sizing scenario.</div>
          ) : (
            <div className={styles.resultGrid}>
              <Result label="Sized bankroll fraction" value={`${(results.sizedFraction * 100).toFixed(2)}%`} note={results.capped ? 'Limited by the 25% research safety cap.' : 'Fractional Kelly after safety cap.'} tone={results.sizedFraction > 0 ? styles.resultPositive : styles.resultNegative} />
              <Result label="Stake amount" value={`$${results.stake.toFixed(2)}`} note="Applied to the bankroll entered above." />
              <Result label="Probability edge" value={`${results.probabilityEdge >= 0 ? '+' : ''}${(results.probabilityEdge * 100).toFixed(2)}pp`} note={`${(results.probability * 100).toFixed(1)}% estimate vs ${(results.impliedProbability * 100).toFixed(1)}% implied.`} tone={results.probabilityEdge > 0 ? styles.resultPositive : styles.resultNegative} />
              <Result label="Expected return / $1" value={`${results.expectedReturn >= 0 ? '+' : ''}${(results.expectedReturn * 100).toFixed(2)}%`} note="At the entered probability and price." tone={results.expectedReturn > 0 ? styles.resultPositive : styles.resultNegative} />
              <Result label="Expected value ($)" value={`${results.expectedReturn * results.stake >= 0 ? '+' : '-'}$${Math.abs(results.expectedReturn * results.stake).toFixed(2)}`} note="A mathematical expectation, not realized profit." tone={results.expectedReturn > 0 ? styles.resultPositive : styles.resultNegative} />
              <Result label="Profit if win" value={`$${results.winProfit.toFixed(2)}`} note={`Full Kelly before fraction: ${(results.fullKelly * 100).toFixed(2)}%.`} />
            </div>
          )}
        </section>

        <div className={styles.formulaStrip}>
          <code>f* = (b·p − (1−p)) / b</code> · The entered Kelly fraction scales <code>f*</code>; this interface then limits the scenario to 25% of bankroll. A useful result still depends on a calibrated probability and an executable price.
        </div>
      </div>
    </section>
  );
}
