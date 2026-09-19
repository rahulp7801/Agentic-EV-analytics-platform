'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ArrowUpRight, Check, FlaskConical, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { BACKTEST_METRICS, formatBacktestMetric, mispricedProps, strategySuggestions,
  type BacktestMetric, type BacktestReport } from '@/lib/backtestLab';
import {forecastChecks, forecastCohort, forecastEvidenceGate, forecastResult, highestConvictionForecast,
  type ForecastBenchmarkBundle} from '@/lib/publicBenchmarks';
import type { EVSignal, Sport } from '@/lib/types';
import {fetchForecasts} from '@/lib/fetchForecasts';
import styles from './BacktestLab.module.css';

type Cohort = 'all' | 'recommendations';
type Props = { sport: Sport; preview?: boolean };
type EvidenceProp = 'all' | 'pass_yds' | 'receptions';
type EvidenceGrade = 'all' | 'correct' | 'missed';
type EvidenceConviction = 'all' | 'highest';

const INITIAL_METRICS: BacktestMetric[] = ['roi', 'brier_score', 'clv_mean'];

async function responseJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, {cache: 'no-store', signal});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `${path} unavailable`);
  return body as T;
}

function cohortTitle(cohort: Cohort) {
  return cohort === 'all' ? 'All eligible predictions' : 'Accepted recommendations';
}

export default function BacktestLab({ sport, preview = false }: Props) {
  const reduceMotion = useReducedMotion();
  const [cohort, setCohort] = useState<Cohort>('all');
  const [selected, setSelected] = useState<BacktestMetric[]>(INITIAL_METRICS);
  const [minimumSample, setMinimumSample] = useState(50);
  const [reports, setReports] = useState<Record<Cohort, BacktestReport | null>>({all:null,recommendations:null});
  const [benchmark, setBenchmark] = useState<ForecastBenchmarkBundle | null>(null);
  const [signals, setSignals] = useState<EVSignal[]>([]);
  const [evidenceProp, setEvidenceProp] = useState<EvidenceProp>('all');
  const [evidenceGrade, setEvidenceGrade] = useState<EvidenceGrade>('all');
  const [evidenceConviction, setEvidenceConviction] = useState<EvidenceConviction>('all');
  const [evidenceLimit, setEvidenceLimit] = useState(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError('');
    const signalRequest = fetchForecasts(sport,controller.signal,'qualified');
    const metricsRequest = Promise.allSettled([
      responseJson<BacktestReport>(`/api/metrics?cohort=all&sport=${sport}`, controller.signal),
      responseJson<BacktestReport>(`/api/metrics?cohort=recommendations&sport=${sport}`, controller.signal),
    ]);
    const [benchmarkEnvelope] = await Promise.allSettled([
      responseJson<{benchmarks: ForecastBenchmarkBundle[]}>(`/api/benchmarks?sport=${sport}`, controller.signal),
    ]);
    if (controller.signal.aborted || request.current !== controller) return;

    setBenchmark(benchmarkEnvelope.status === 'fulfilled' && Array.isArray(benchmarkEnvelope.value.benchmarks)
      ? benchmarkEnvelope.value.benchmarks[0] ?? null : null);
    setLoading(false);
    const [all, recommendations] = await metricsRequest;
    if (controller.signal.aborted || request.current !== controller) return;
    setReports({
      all: all.status === 'fulfilled' ? all.value : null,
      recommendations: recommendations.status === 'fulfilled' ? recommendations.value : null,
    });
    const unavailable = [all, recommendations].filter(result => result.status === 'rejected').length;
    setError(unavailable ? `${unavailable === 2 ? 'League replay snapshots are' : 'One replay snapshot is'} not published yet. Available evidence remains visible.` : '');
    const signalEnvelope = await Promise.allSettled([signalRequest]);
    if (controller.signal.aborted || request.current !== controller) return;
    const liveSignals = signalEnvelope[0];
    setSignals(liveSignals.status === 'fulfilled' && Array.isArray(liveSignals.value.signals)
      ? liveSignals.value.signals : []);
  }, [sport]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(timer);
      request.current?.abort();
    };
  }, [load]);

  const report = reports[cohort];
  const suggestions = useMemo(() => strategySuggestions(
    Object.values(reports).filter((value): value is BacktestReport => value !== null), selected, minimumSample),
  [reports, selected, minimumSample]);
  const candidates = useMemo(() => mispricedProps(signals, sport), [signals, sport]);
  const evidenceScope = useMemo(() => (benchmark?.records ?? [])
    .filter(record => evidenceProp === 'all' || record.prop_type === evidenceProp)
    .filter(record => evidenceConviction === 'all' || highestConvictionForecast(record)),
  [benchmark, evidenceConviction, evidenceProp]);
  const evidence = useMemo(() => evidenceScope
    .filter(record => evidenceGrade === 'all'
      || forecastResult(record).correct === (evidenceGrade === 'correct'))
    .sort((left,right) => right.game_start_time.localeCompare(left.game_start_time)
      || left.player_name.localeCompare(right.player_name)),
  [evidenceGrade, evidenceScope]);
  const evidenceStats = useMemo(() => forecastCohort(evidenceScope), [evidenceScope]);
  const clearsEvidenceFloor = forecastEvidenceGate(evidenceStats);
  const displayedEvidence = evidence.slice(0, preview ? 6 : evidenceLimit);

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

      {benchmark && <div className={styles.benchmarkPanel}>
        <div className={styles.benchmarkHeading}>
          <div><span><ShieldCheck /> Verified retrospective benchmark</span><h3>{benchmark.title}</h3>
            <p>{benchmark.evaluation_scope}</p></div>
          <div><strong>{benchmark.game_count} games</strong><span>{benchmark.outcome_record_count} outcome rows</span></div>
        </div>
        <div className={styles.benchmarkGrid}>{benchmark.benchmarks.map(item => {
          const checks=forecastChecks(item);
          const passed=Object.values(checks).filter(Boolean).length;
          const itemRecords=benchmark.records.filter(record=>record.prop_type===item.prop_type);
          const itemCorrect=itemRecords.filter(record=>forecastResult(record).correct).length;
          return <article key={item.prop_type}>
            <div className={styles.benchmarkCardTop}><div><span>{item.label} · over {item.research_threshold}</span>
              <strong>{item.evaluated_count} verified forecasts</strong></div>
              <em data-pass={passed >= 2}>{passed >= 2 ? `${passed} forecast checks passed` : 'Did not clear checks'}</em></div>
            <div className={styles.benchmarkMetrics}>
              <div><span>Brier</span><strong>{item.brier_score.toFixed(3)}</strong><small>{item.brier_score_game_cluster_interval.map(value=>value.toFixed(3)).join('–')}</small></div>
              <div><span>Log loss</span><strong>{item.log_loss.toFixed(3)}</strong><small>{item.log_loss_game_cluster_interval.map(value=>value.toFixed(3)).join('–')}</small></div>
              <div><span>Calibration</span><strong>{(item.calibration_error*100).toFixed(1)}%</strong><small>{checks.calibration ? '≤5% check passed' : '>5% check not passed'}</small></div>
              <div><span>50% direction</span><strong>{((itemCorrect/itemRecords.length)*100).toFixed(1)}%</strong><small>{itemCorrect}/{itemRecords.length} calls correct</small></div>
            </div>
          </article>;
        })}</div>
        <div className={styles.evidenceHeading}>
          <div><span>Prediction-level evidence</span><h4>Every forecast, graded.</h4>
            <p>The model call uses a transparent 50% probability cutoff. Final stats grade the fixed research threshold; this is directional forecast accuracy, not betting profit.</p></div>
          <div><strong>{evidenceStats.correct} / {evidenceStats.sample}</strong><span>{evidenceConviction==='highest' ? 'highest-conviction' : '50% model'} calls correct</span>
            <small>{evidenceStats.hit_rate===null ? 'No scored forecasts' : `${(evidenceStats.hit_rate*100).toFixed(1)}% directional accuracy`}</small></div>
        </div>
        <div className={styles.convictionProof} role="status">
          <div><span>Selected evidence</span><strong>{evidenceStats.hit_rate===null ? 'Unavailable' : `${(evidenceStats.hit_rate*100).toFixed(1)}%`}</strong><small>{evidenceStats.correct}/{evidenceStats.sample} correct</small></div>
          <div><span>95% game-cluster interval</span><strong>{evidenceStats.game_cluster_interval ? evidenceStats.game_cluster_interval.map(value=>`${(value*100).toFixed(1)}%`).join('–') : 'Unavailable'}</strong><small>{evidenceStats.game_count} game clusters</small></div>
          <p data-clears-evidence-floor={clearsEvidenceFloor}>{clearsEvidenceFloor ? 'Observed cohort clears the 65% evidence floor at the lower game-cluster bound. ' : ''}{evidenceConviction==='highest' ? 'Highest conviction requires at least 60% model probability on the called side. This descriptive filter was inspected after outcomes and is not a priced sportsbook acceptance rule.' : 'All natural Over/Under calls are included. Correct and missed filters below never change this denominator.'}</p>
        </div>
        <div className={styles.evidenceFilters}>
          <div aria-label="Evidence conviction filter">
            {([['all','All forecasts'],['highest','Highest conviction']] as const).map(([value,label]) =>
              <button type="button" key={value} aria-pressed={evidenceConviction===value} onClick={()=>{setEvidenceConviction(value);setEvidenceLimit(20);}}>{label}</button>)}
          </div>
          <div aria-label="Evidence prop filter">
            {([['all','All props'],['pass_yds','Passing yards'],['receptions','Receptions']] as const).map(([value,label]) =>
              <button type="button" key={value} aria-pressed={evidenceProp===value} onClick={()=>{setEvidenceProp(value);setEvidenceLimit(20);}}>{label}</button>)}
          </div>
          <div aria-label="Evidence grade filter">
            {([['all','All results'],['correct','Correct'],['missed','Missed']] as const).map(([value,label]) =>
              <button type="button" key={value} aria-pressed={evidenceGrade===value} onClick={()=>{setEvidenceGrade(value);setEvidenceLimit(20);}}>{label}</button>)}
          </div>
          <span>{evidence.length} match · {evidenceStats.sample} in performance denominator</span>
        </div>
        <div className={styles.evidenceScroll} role="region" aria-label="Verified forecast results" tabIndex={0}>
          <table className={styles.evidenceTable}>
            <thead><tr><th>Date</th><th>Player / matchup</th><th>Research test</th><th>Cutoff forecast</th><th>Final stat</th><th>Grade</th><th>Evidence</th></tr></thead>
            <tbody>{displayedEvidence.map(record=>{
              const result=forecastResult(record);
              const label=benchmark.benchmarks.find(item=>item.prop_type===record.prop_type)?.label ?? record.prop_type;
              return <tr key={record.id}>
                <td><time dateTime={record.game_start_time}>{new Date(`${record.game_date}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',day:'numeric'})}</time></td>
                <td><strong>{record.player_name}</strong><small>{record.team} vs {record.opponent}</small></td>
                <td><strong>Over {record.research_threshold}</strong><small>{label}</small></td>
                <td><strong>{result.side==='over' ? 'Over' : 'Under'}</strong><small>P(over) {(record.model_probability*100).toFixed(1)}% · n={record.sample_size}</small></td>
                <td><strong>{record.actual_value}</strong><small>{record.outcome ? 'Over' : 'Under'} threshold</small></td>
                <td><em data-correct={result.correct}>{result.correct ? 'Correct' : 'Missed'}</em></td>
                <td><a href={record.source_url} target="_blank" rel="noreferrer">ESPN event <ArrowUpRight /></a><code title={record.source_sha256}>{record.source_sha256.slice(0,8)}…</code></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        {!displayedEvidence.length && <div className={styles.emptyEvidence}>No verified forecasts match these filters.</div>}
        <div className={styles.evidenceActions}>
          {!preview && evidenceLimit<evidence.length && <button type="button" onClick={()=>setEvidenceLimit(limit=>limit+20)}>Show 20 more</button>}
          {preview && <a href="/terminal#nfl/backtest">Open all {benchmark.records.length} verified results <ArrowUpRight /></a>}
          <span>Source hashes bind each result to its archived ESPN response.</span>
        </div>
        <div className={styles.benchmarkFoot}><span>{benchmark.price_scope}</span><code>dataset {benchmark.dataset_sha256.slice(0,12)}…</code></div>
      </div>}

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
