'use client';
import { useEffect, useState } from 'react';
export default function Performance() {
  const [metrics, setMetrics] = useState<Record<string, number | string | null> | null>(null);
  useEffect(() => { fetch('/api/metrics').then(r => r.json()).then(setMetrics).catch(() => setMetrics({error: 'Metrics unavailable'})); }, []);
  const value = (key: string, percent = false, unit = '%') => typeof metrics?.[key] === 'number'
    ? ((metrics[key] as number) * (percent ? 100 : 1)).toFixed(percent ? 1 : 3) + (percent ? unit : '') : 'Unavailable';
  return <section style={{padding: 12, border: '1px solid var(--border-dim)', margin: '8px 0'}}>
    <div className="section-header">Historical evaluation · all predictions · unit stakes</div>
    {metrics?.error ? <p>{String(metrics.error)}</p> : <>
      <p>Settled: {metrics?.settled_count ?? 0} · Pending: {metrics?.pending_count ?? 0} · Calibration sample: {metrics?.calibration_count ?? 0}</p>
      <p>ROI: {value('roi', true)} · Hit rate: {value('hit_rate', true)} · Brier: {value('brier_score')} · Log loss: {value('log_loss')}</p>
      <p>CLV: {value('clv_mean', true, 'pp')} ({metrics?.clv_count ?? 0} matched quotes). Missing outcomes remain unsettled.</p>
    </>}
  </section>;
}
