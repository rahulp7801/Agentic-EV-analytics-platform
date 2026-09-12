'use client';

import { useEffect, useState } from 'react';

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

function MetricBlock({ title, metrics }: { title: string; metrics: MetricReport | null }) {
  if (!metrics) return <article><h3>{title}</h3><p>Metrics loading…</p></article>;
  if (typeof metrics.error === 'string') return <article><h3>{title}</h3><p>{metrics.error}</p></article>;
  return <article>
    <h3>{title}</h3>
    <p>Settled: {count(metrics, 'settled_count')} · Pending: {count(metrics, 'pending_count')} · Calibration sample: {count(metrics, 'calibration_count')}</p>
    <p>ROI: {value(metrics, 'roi', true)} · Hit rate: {value(metrics, 'hit_rate', true)} · Brier: {value(metrics, 'brier_score')} · Log loss: {value(metrics, 'log_loss')}</p>
    <p>Brier benchmarks: always predict loss {value(metrics, 'baseline_zero_brier')} · 50/50 {value(metrics, 'baseline_50_brier')} · always predict win {value(metrics, 'baseline_one_brier')}.</p>
    <p>Scored outcomes: {count(metrics, 'calibration_positive_count')} wins among {count(metrics, 'calibration_count')} forecasts. Lower Brier is better. Benchmarks use the same sample, excluding pushes, voids, pending outcomes and missing forecasts.</p>
    <p>CLV: {value(metrics, 'clv_mean', true, 'pp')} ({count(metrics, 'clv_count')} matched quotes). Missing outcomes remain unsettled.</p>
  </article>;
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
    ? metrics.all.model_version : 'model cohort unavailable';
  return <section style={{padding: 12, border: '1px solid var(--border-dim)', margin: '8px 0'}}>
    <div className="section-header">Historical evaluation · {version}</div>
    <MetricBlock title="All eligible predictions · unit stakes" metrics={metrics.all} />
    <MetricBlock title="Accepted recommendations · recorded stake fractions" metrics={metrics.recommendations} />
  </section>;
}
