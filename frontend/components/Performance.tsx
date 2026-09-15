'use client';

import { useEffect, useState } from 'react';
import { metricInterval, rateInterval } from '@/lib/performanceMetrics';
import styles from './ResearchViews.module.css';

type MetricReport = Record<string, unknown>;

function value(metrics: MetricReport, key: string, percent = false, unit = '%') {
  const raw = metrics[key];
  return typeof raw === 'number'
    ? (raw * (percent ? 100 : 1)).toFixed(percent ? 1 : 3) + (percent ? unit : '')
    : 'Unavailable';
}

function count(metrics: MetricReport, key: string) {
  return typeof metrics[key] === 'number' ? String(metrics[key]) : 'Unavailable';
}

function KeyMetric({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className={styles.keyMetric}><span>{label}</span><strong>{children}</strong></div>;
}

function MetricBlock({ title, metrics }: { title: string; metrics: MetricReport | null }) {
  if (!metrics) {
    return <article className={styles.metricBlock}><p className={styles.metricError}>Loading evaluation…</p></article>;
  }
  if (typeof metrics.error === 'string') {
    return <article className={styles.metricBlock}><p className={styles.metricError}>{metrics.error}</p></article>;
  }

  return (
    <article className={styles.metricBlock}>
      <header className={styles.metricBlockHeader}>
        <h3>{title}</h3>
        <span>{count(metrics, 'settled_count')} settled · {count(metrics, 'pending_count')} pending</span>
      </header>
      <div className={styles.keyMetrics}>
        <KeyMetric label="ROI">{value(metrics, 'roi', true)}</KeyMetric>
        <KeyMetric label="Hit rate">{value(metrics, 'hit_rate', true)}</KeyMetric>
        <KeyMetric label="Brier">{value(metrics, 'brier_score')}</KeyMetric>
        <KeyMetric label="CLV">{value(metrics, 'clv_mean', true, 'pp')}</KeyMetric>
      </div>
      <div className={styles.metricNotes}>
        <p><b>95% intervals</b> · ROI {metricInterval(metrics, 'roi_game_cluster_interval', true)} · hit rate {rateInterval(metrics, 'hit_rate_game_cluster_interval')} · Brier {metricInterval(metrics, 'brier_score_game_cluster_interval')} · CLV {metricInterval(metrics, 'clv_mean_game_cluster_interval', true, 'pp')}</p>
        <p><b>Calibration</b> · n={count(metrics, 'calibration_count')} · error {value(metrics, 'calibration_error')} · log loss {value(metrics, 'log_loss')} · 50/50 Brier benchmark {value(metrics, 'baseline_50_brier')}</p>
      </div>
    </article>
  );
}

export default function Performance() {
  const [metrics, setMetrics] = useState<{ all: MetricReport | null; recommendations: MetricReport | null }>({
    all: null,
    recommendations: null,
  });

  useEffect(() => {
    let active = true;
    Promise.all(['all', 'recommendations'].map(async cohort => {
      const response = await fetch(`/api/metrics?cohort=${cohort}`);
      return response.json() as Promise<MetricReport>;
    })).then(([all, recommendations]) => {
      if (active) setMetrics({ all, recommendations });
    }).catch(() => {
      if (active) {
        const error = { error: 'Metrics unavailable' };
        setMetrics({ all: error, recommendations: error });
      }
    });
    return () => { active = false; };
  }, []);

  const version = metrics.all && typeof metrics.all.model_version === 'string'
    ? metrics.all.model_version
    : 'model cohort unavailable';

  return (
    <section className={styles.performance} aria-labelledby="evaluation-title">
      <header className={styles.performanceHeader}>
        <h2 id="evaluation-title">Historical evaluation</h2>
        <span>{version} · game-cluster intervals where available</span>
      </header>
      <div className={styles.metricGrid}>
        <MetricBlock title="All eligible predictions · unit stakes" metrics={metrics.all} />
        <MetricBlock title="Accepted recommendations · recorded stakes" metrics={metrics.recommendations} />
      </div>
    </section>
  );
}
