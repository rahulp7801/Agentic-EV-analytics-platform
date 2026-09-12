import type { MetricCohort } from './metricCohort';

type JsonRecord = Record<string, unknown>;

const BINOMIAL_METHOD = 'Nominal 95% Wilson interval; treats decided selections as independent and does not adjust for shared games or players.';
const CLUSTER_METHOD = '95% game-cluster robust t interval; requires at least two distinct games. It allows arbitrary dependence within a game but does not adjust for the same player appearing across games.';
const CLOSING_LINE_NOTE = 'CLV is same-line raw implied-probability movement; requires entry < close < start.';
const SELECTION_POLICY = 'Earliest eligible prediction per game/player/market/side/line within the selected cohort.';
const PROFIT_SCOPE = 'Hypothetical recorded-stake replay, not executed bets or realized account profit.';

function record(value: unknown): JsonRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid metrics');
  return value as JsonRecord;
}

function count(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new Error('Invalid metrics');
  return value as number;
}

function metric(value: unknown, minimum = Number.NEGATIVE_INFINITY,
    maximum = Number.POSITIVE_INFINITY): number | null {
  if (value === null) return null;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error('Invalid metrics');
  }
  return value;
}

function optionalMetric(value: unknown, minimum = Number.NEGATIVE_INFINITY,
    maximum = Number.POSITIVE_INFINITY): number | null {
  return value === undefined ? null : metric(value, minimum, maximum);
}

function interval(value: unknown, minimum = Number.NEGATIVE_INFINITY,
    maximum = Number.POSITIVE_INFINITY): [number, number] | null {
  if (value === null) return null;
  if (!Array.isArray(value) || value.length !== 2) throw new Error('Invalid metrics');
  const lower = metric(value[0], minimum, maximum);
  const upper = metric(value[1], minimum, maximum);
  if (lower === null || upper === null || lower > upper) throw new Error('Invalid metrics');
  return [lower, upper];
}

function optionalInterval(value: unknown, minimum = Number.NEGATIVE_INFINITY,
    maximum = Number.POSITIVE_INFINITY): [number, number] | null {
  return value === undefined ? null : interval(value, minimum, maximum);
}

function requiredMetric(value: unknown, minimum = Number.NEGATIVE_INFINITY,
    maximum = Number.POSITIVE_INFINITY): number {
  const result = metric(value, minimum, maximum);
  if (result === null) throw new Error('Invalid metrics');
  return result;
}

function modelVersion(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value)) {
    throw new Error('Invalid metrics');
  }
  return value;
}

function calibration(value: unknown) {
  if (!Array.isArray(value) || value.length > 10) throw new Error('Invalid metrics');
  return value.map(item => {
    const bin = record(item);
    const lower = requiredMetric(bin.lower, 0, 1);
    const upper = requiredMetric(bin.upper, 0, 1);
    if (lower >= upper) throw new Error('Invalid metrics');
    return {lower, upper, count: count(bin.count), predicted: requiredMetric(bin.predicted, 0, 1),
      observed: requiredMetric(bin.observed, 0, 1), observed_interval: interval(bin.observed_interval, 0, 1)};
  });
}

function clusterMetrics(data: JsonRecord) {
  const keys = ['roi_game_cluster_interval', 'roi_game_cluster_count',
    'hit_rate_game_cluster_interval', 'hit_rate_game_cluster_count',
    'brier_score_game_cluster_interval', 'log_loss_game_cluster_interval',
    'calibration_game_cluster_count', 'clv_mean_game_cluster_interval',
    'clv_game_cluster_count'];
  const present = keys.filter(key => data[key] !== undefined);
  if (present.length === 0) return {};
  if (present.length !== keys.length) throw new Error('Invalid metrics');
  const result = {
    roi_game_cluster_interval: interval(data.roi_game_cluster_interval, -1),
    roi_game_cluster_count: count(data.roi_game_cluster_count),
    hit_rate_game_cluster_interval: interval(data.hit_rate_game_cluster_interval, 0, 1),
    hit_rate_game_cluster_count: count(data.hit_rate_game_cluster_count),
    brier_score_game_cluster_interval: interval(data.brier_score_game_cluster_interval, 0, 1),
    log_loss_game_cluster_interval: interval(data.log_loss_game_cluster_interval, 0),
    calibration_game_cluster_count: count(data.calibration_game_cluster_count),
    clv_mean_game_cluster_interval: interval(data.clv_mean_game_cluster_interval, -1, 1),
    clv_game_cluster_count: count(data.clv_game_cluster_count),
    game_cluster_interval_method: CLUSTER_METHOD,
  };
  for (const [countKey, intervalKey] of [
    ['roi_game_cluster_count', 'roi_game_cluster_interval'],
    ['hit_rate_game_cluster_count', 'hit_rate_game_cluster_interval'],
    ['calibration_game_cluster_count', 'brier_score_game_cluster_interval'],
    ['calibration_game_cluster_count', 'log_loss_game_cluster_interval'],
    ['clv_game_cluster_count', 'clv_mean_game_cluster_interval'],
  ] as const) {
    if (result[intervalKey] !== null && result[countKey] < 2) throw new Error('Invalid metrics');
  }
  return result;
}

/** Validate and project the only evaluation shape allowed across the public API boundary. */
export function publicMetrics(value: unknown, expected: MetricCohort) {
  const data = record(value);
  const cohort = expected === 'all' ? 'all_predictions' : 'recommendations';
  if (data.cohort !== cohort) throw new Error('Invalid metrics');
  const sampleSize = count(data.sample_size);
  const settledCount = count(data.settled_count);
  const pendingCount = count(data.pending_count);
  const voidCount = count(data.void_count);
  const decidedCount = count(data.decided_count);
  const calibrationCount = count(data.calibration_count);
  const positiveCount = count(data.calibration_positive_count);
  const bins = calibration(data.calibration);
  if (settledCount + pendingCount + voidCount !== sampleSize || decidedCount > settledCount
      || calibrationCount > decidedCount || positiveCount > calibrationCount
      || bins.reduce((total, bin) => total + bin.count, 0) !== calibrationCount) {
    throw new Error('Invalid metrics');
  }
  const hitRate = metric(data.hit_rate, 0, 1);
  const hitRateInterval = optionalInterval(data.hit_rate_interval, 0, 1);
  if (decidedCount === 0 ? hitRate !== null || hitRateInterval !== null : hitRate === null) {
    throw new Error('Invalid metrics');
  }
  const clvCount = count(data.clv_count);
  const clvMean = metric(data.clv_mean, -1, 1);
  if ((clvCount === 0) !== (clvMean === null)) throw new Error('Invalid metrics');
  const brierScore = metric(data.brier_score, 0, 1);
  const logLoss = metric(data.log_loss, 0);
  const calibrationError = optionalMetric(data.calibration_error, 0, 1);
  const baselineZero = metric(data.baseline_zero_brier, 0, 1);
  const baselineHalf = metric(data.baseline_50_brier, 0, 1);
  const baselineOne = metric(data.baseline_one_brier, 0, 1);
  const coreScores = [brierScore, logLoss, baselineZero, baselineHalf, baselineOne];
  if (calibrationCount === 0 ? [...coreScores, calibrationError].some(item => item !== null)
      : coreScores.some(item => item === null)) throw new Error('Invalid metrics');
  if (calibrationCount > 0 && (Math.abs((baselineZero as number)-positiveCount/calibrationCount) > 1e-12
      || Math.abs((baselineOne as number)-(calibrationCount-positiveCount)/calibrationCount) > 1e-12
      || Math.abs((baselineHalf as number)-0.25) > 1e-12)) throw new Error('Invalid metrics');
  if (!Array.isArray(data.available_model_versions) || data.available_model_versions.length > 64) {
    throw new Error('Invalid metrics');
  }
  const versions = data.available_model_versions.map(value => {
    const version = modelVersion(value);
    if (version === null) throw new Error('Invalid metrics');
    return version;
  });
  if (new Set(versions).size !== versions.length) throw new Error('Invalid metrics');
  return {
    cohort,
    model_version: modelVersion(data.model_version),
    available_model_versions: versions,
    sample_size: sampleSize, settled_count: settledCount, decided_count: decidedCount,
    pending_count: pendingCount, void_count: voidCount,
    excluded_missing_metadata: count(data.excluded_missing_metadata),
    duplicate_predictions: count(data.duplicate_predictions),
    excluded_closing_quotes: count(data.excluded_closing_quotes),
    unverified_settlements: count(data.unverified_settlements),
    roi: metric(data.roi, -1), hit_rate: hitRate, hit_rate_interval: hitRateInterval,
    clv_mean: clvMean, clv_count: clvCount,
    calibration_count: calibrationCount, calibration_positive_count: positiveCount,
    brier_score: brierScore, log_loss: logLoss, calibration_error: calibrationError,
    baseline_zero_brier: baselineZero, baseline_50_brier: baselineHalf,
    baseline_one_brier: baselineOne, calibration: bins,
    ...clusterMetrics(data),
    binomial_interval_method: BINOMIAL_METHOD,
    closing_line_note: CLOSING_LINE_NOTE,
    selection_policy: SELECTION_POLICY,
    profit_scope: PROFIT_SCOPE,
  };
}
