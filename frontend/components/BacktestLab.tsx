'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ArrowUpRight, Check, FlaskConical, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { BACKTEST_METRICS, formatBacktestMetric, mispricedProps, strategySuggestions,
  type BacktestMetric, type BacktestReport } from '@/lib/backtestLab';
import type { EVSignal, Sport } from '@/lib/types';
import styles from './BacktestLab.module.css';

type Cohort = 'all' | 'recommendations';
type Props = { sport: Sport; preview?: boolean };

const INITIAL_METRICS: BacktestMetric[] = ['roi', 'brier_score', 'clv_mean'];

function cohortTitle(cohort: Cohort) {
  return cohort === 'all' ? 'All eligible predictions' : 'Accepted recommendations';
}

export default function BacktestLab({ sport, preview = false }: Props) {
  const reduceMotion = useReducedMotion();
  const [cohort, setCohort] = useState<Cohort>('all');
  const [selected, setSelected] = useState<BacktestMetric[]>(INITIAL_METRICS);
  const [minimumSample, setMinimumSample] = useState(50);
  const [reports, setReports] = useState<Record<Cohort, BacktestReport | null>>({all:null,recommendations:null});
  const [signals, setSignals] = useState<EVSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [allResponse, recommendationsResponse, signalsResponse] = await Promise.all([
        fetch(`/api/metrics?cohort=all&sport=${sport}`, {cache:'no-store'}),
        fetch(`/api/metrics?cohort=recommendations&sport=${sport}`, {cache:'no-store'}),
        fetch(`/api/signals?sport=${sport}`, {cache:'no-store'}),
      ]);
      const [all, recommendations, signalEnvelope] = await Promise.all([
        allResponse.json(), recommendationsResponse.json(), signalsResponse.json(),
      ]);
      if (!allResponse.ok || !recommendationsResponse.ok) throw new Error('League replay snapshot is not published yet.');
      setReports({all, recommendations});
      setSignals(signalsResponse.ok && Array.isArray(signalEnvelope.signals) ? signalEnvelope.signals : []);
    } catch (loadError) {
      setReports({all:null,recommendations:null});
      setSignals([]);
      setError(loadError instanceof Error ? loadError.message : 'Backtest evidence is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [sport]);

  useEffect(() => { void load(); }, [load]);

  const report = reports[cohort];
  const suggestions = useMemo(() => strategySuggestions(
    Object.values(reports).filter((value): value is BacktestReport => value !== null), selected, minimumSample),
  [reports, selected, minimumSample]);
  const candidates = useMemo(() => mispricedProps(signals, sport), [signals, sport]);

  function toggleMetric(metric: BacktestMetric) {
    setSelected(current => current.includes(metric)
      ? (current.length === 1 ? current : current.filter(item => item !== metric))
      : [...current, metric]);
  }

  return (
    <section className={`${styles.lab} ${preview ? styles.preview : ''}`} aria-labelledby={preview ? 'backtest-demo-title' : 'backtest-lab-title'}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}><FlaskConical /> Recorded evidence lab</span>
          <h2 id={preview ? 'backtest-demo-title' : 'backtest-lab-title'}>{preview ? 'Try the replay engine.' : 'Backtest lab'}</h2>
          <p>Choose the evidence you care about. Replays use recorded pregame prices and verified outcomes; unavailable results stay unavailable.</p>
        </div>
        <button className={styles.refresh} type="button" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={loading ? styles.spinning : ''} /> {loading ? 'Reading evidence' : 'Refresh replay'}
        </button>
      </header>

      <div className={styles.controls}>
        <div className={styles.controlGroup}>
          <span>Replay cohort</span>
          <div className={styles.segmented}>
            {(['all','recommendations'] as Cohort[]).map(value => (
              <button type="button" key={value} aria-pressed={cohort === value} onClick={() => setCohort(value)}>
                {value === 'all' ? 'All predictions' : 'Recommendations'}
              </button>
            ))}
          </div>
        </div>
        <div className={styles.controlGroup}>
          <span>Minimum settled sample</span>
          <div className={styles.segmented}>
            {[30,50,100].map(value => <button type="button" key={value} aria-pressed={minimumSample === value}
              onClick={() => setMinimumSample(value)}>{value}</button>)}
          </div>
        </div>
      </div>

      <div className={styles.metricToggles} aria-label="Backtest metrics">
        {BACKTEST_METRICS.map(metric => {
          const active = selected.includes(metric.key);
          return <button type="button" key={metric.key} aria-pressed={active} onClick={() => toggleMetric(metric.key)}>
            <span>{active && <Check />}</span><div><strong>{metric.label}</strong><small>{metric.short}</small></div>
          </button>;
        })}
      </div>

      {error && <div className={styles.notice} role="status"><ShieldCheck /> <span><strong>Replay waiting for published evidence.</strong>{error}</span></div>}

      <div className={styles.workspace}>
        <div className={styles.resultPanel}>
          <div className={styles.panelHeading}>
            <div><span>{sport.toUpperCase()} · {cohortTitle(cohort)}</span><strong>{report?.model_version ?? 'Model cohort unavailable'}</strong></div>
            <span>{report?.settled_count ?? 0} settled / {report?.pending_count ?? 0} pending</span>
          </div>
          <div className={styles.metricGrid}>
            <AnimatePresence mode="popLayout" initial={false}>
              {selected.map(key => {
                const definition = BACKTEST_METRICS.find(metric => metric.key === key)!;
                const value = report ? report[key] : null;
                return <motion.article layout key={key} initial={reduceMotion ? false : {opacity:0,y:12}}
                  animate={{opacity:1,y:0}} exit={{opacity:0,scale:.96}} transition={{duration:.22}}>
                  <span>{definition.label}</span><strong>{formatBacktestMetric(key, value)}</strong>
                  <small>{report?.settled_count ? definition.short : 'Needs verified settled outcomes'}</small>
                </motion.article>;
              })}
            </AnimatePresence>
          </div>
          <div className={styles.sampleTrack}>
            <div><span>Settled evidence</span><strong>{report?.decided_count ?? 0} / {minimumSample} minimum</strong></div>
            <i><b style={{width:`${Math.min(100, ((report?.decided_count ?? 0) / minimumSample) * 100)}%`}} /></i>
          </div>
        </div>

        <aside className={styles.suggestionPanel}>
          <span className={styles.eyebrow}><Sparkles /> Evidence-backed combinations</span>
          {suggestions.length ? suggestions.slice(0,2).map(candidate => (
            <article key={candidate.report.cohort}>
              <strong>{candidate.report.cohort === 'recommendations' ? 'Recorded recommendations' : 'All predictions'}</strong>
              <p>{candidate.metrics.map(metric => BACKTEST_METRICS.find(item => item.key === metric)?.label).join(' + ')}</p>
              <small>{candidate.report.decided_count} decided selections · uncertainty thresholds passed</small>
            </article>
          )) : <div className={styles.emptySuggestion}><strong>No validated combination yet.</strong><p>Suggestions require at least {minimumSample} decided selections and multiple uncertainty-aware checks. Point estimates alone do not qualify.</p></div>}
        </aside>
      </div>

      <div className={styles.candidates}>
        <div className={styles.candidateHeading}>
          <div><span>Current model-price disagreements</span><strong>{candidates.length} eligible</strong></div>
          <p>Fresh recorded sportsbook props with positive expected return, sufficient history, and a reported interval. Research leads only.</p>
        </div>
        {candidates.length ? <div className={styles.candidateList}>{candidates.slice(0, preview ? 3 : 6).map(signal => (
          <article key={signal.id}>
            <div><span>{signal.sport.toUpperCase()} · {signal.sportsbook}</span><strong>{signal.player}</strong><small>{signal.direction} {signal.line} {signal.prop_type.replaceAll('_',' ')}</small></div>
            <div><span>Model / price</span><strong>{(signal.true_prob*100).toFixed(1)}% / {(signal.implied_prob*100).toFixed(1)}%</strong><small>+{(signal.ev_pct*100).toFixed(1)}pp disagreement</small></div>
            <ArrowUpRight aria-hidden="true" />
          </article>
        ))}</div> : <div className={styles.emptyCandidates}>No fresh eligible model-price disagreement is published for this league.</div>}
      </div>
    </section>
  );
}
