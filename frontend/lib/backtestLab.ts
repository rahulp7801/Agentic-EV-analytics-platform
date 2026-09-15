import type { EVSignal, Sport } from './types';

export type BacktestMetric = 'roi' | 'hit_rate' | 'brier_score' | 'log_loss' | 'calibration_error' | 'clv_mean';

export const BACKTEST_METRICS: { key: BacktestMetric; label: string; short: string }[] = [
  { key: 'roi', label: 'Replay ROI', short: 'Return at recorded price' },
  { key: 'hit_rate', label: 'Hit rate', short: 'Decided selection accuracy' },
  { key: 'brier_score', label: 'Brier score', short: 'Probability accuracy' },
  { key: 'log_loss', label: 'Log loss', short: 'Confidence penalty' },
  { key: 'calibration_error', label: 'Calibration', short: 'Forecast reliability' },
  { key: 'clv_mean', label: 'Closing value', short: 'Entry-to-close movement' },
];

export type BacktestReport = {
  cohort: 'all_predictions' | 'recommendations';
  sport: 'all' | Sport;
  model_version: string | null;
  sample_size: number;
  settled_count: number;
  decided_count: number;
  pending_count: number;
  excluded_missing_metadata: number;
  roi: number | null;
  hit_rate: number | null;
  brier_score: number | null;
  log_loss: number | null;
  calibration_error: number | null;
  calibration_count: number;
  clv_mean: number | null;
  clv_count: number;
  baseline_50_brier: number | null;
  roi_game_cluster_interval?: [number, number] | null;
  brier_score_game_cluster_interval?: [number, number] | null;
  log_loss_game_cluster_interval?: [number, number] | null;
  clv_mean_game_cluster_interval?: [number, number] | null;
};

export function metricValue(report: BacktestReport, metric: BacktestMetric) {
  return report[metric];
}

function supportedMetrics(report: BacktestReport, selected: BacktestMetric[], minimumSample: number) {
  if (report.decided_count < minimumSample) return [];
  const passed: BacktestMetric[] = [];
  if (selected.includes('roi') && report.roi_game_cluster_interval?.[0] !== undefined
      && report.roi_game_cluster_interval[0] > 0) passed.push('roi');
  if (selected.includes('brier_score') && report.brier_score_game_cluster_interval?.[1] !== undefined
      && report.baseline_50_brier !== null
      && report.brier_score_game_cluster_interval[1] < report.baseline_50_brier) passed.push('brier_score');
  if (selected.includes('log_loss') && report.log_loss_game_cluster_interval?.[1] !== undefined
      && report.log_loss_game_cluster_interval[1] < Math.log(2)) passed.push('log_loss');
  if (selected.includes('clv_mean') && report.clv_mean_game_cluster_interval?.[0] !== undefined
      && report.clv_mean_game_cluster_interval[0] > 0) passed.push('clv_mean');
  if (selected.includes('calibration_error') && report.calibration_count >= minimumSample
      && report.calibration_error !== null && report.calibration_error <= 0.05) passed.push('calibration_error');
  return passed;
}

export function strategySuggestions(reports: BacktestReport[], selected: BacktestMetric[], minimumSample: number) {
  return reports.map(report => ({report, metrics: supportedMetrics(report, selected, minimumSample)}))
    .filter(candidate => candidate.metrics.length >= 2)
    .sort((left, right) => right.metrics.length - left.metrics.length
      || right.report.decided_count - left.report.decided_count);
}

export function mispricedProps(signals: EVSignal[], sport: Sport, now = Date.now(), limit = 6) {
  return signals.filter(signal => signal.sport === sport && signal.gated === false
      && typeof signal.expected_return === 'number' && signal.expected_return > 0
      && signal.ev_pct > 0 && signal.sample_size !== undefined && signal.sample_size >= 20
      && Array.isArray(signal.confidence_interval)
      && Date.parse(signal.snapped_at) <= now && now - Date.parse(signal.snapped_at) <= 300_000
      && Date.parse(signal.game_start_time ?? '') > now)
    .sort((left, right) => (right.expected_return ?? 0) - (left.expected_return ?? 0)
      || right.ev_pct - left.ev_pct)
    .slice(0, Math.max(0, Math.min(20, limit)));
}

export function formatBacktestMetric(metric: BacktestMetric, value: number | null) {
  if (value === null) return 'Unavailable';
  if (metric === 'roi' || metric === 'hit_rate') return `${(value * 100).toFixed(1)}%`;
  if (metric === 'clv_mean') return `${(value * 100).toFixed(2)}pp`;
  return value.toFixed(3);
}
