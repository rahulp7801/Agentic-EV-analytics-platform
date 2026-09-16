export type ForecastBenchmark = {
  prop_type: 'pass_yds' | 'receptions';
  label: string;
  research_threshold: number;
  candidate_count: number;
  evaluated_count: number;
  missing_or_small_sample: number;
  unknown_or_ambiguous_player: number;
  calibration_count: number;
  calibration_positive_count: number;
  brier_score: number;
  log_loss: number;
  calibration_error: number;
  baseline_50_brier: number;
  game_cluster_count: number;
  brier_score_game_cluster_interval: [number, number];
  log_loss_game_cluster_interval: [number, number];
};

export type ForecastBenchmarkBundle = {
  schema_version: 1;
  id: string;
  sport: 'nfl';
  title: string;
  start_date: string;
  end_date: string;
  retrieved_at: string;
  model_version: string;
  game_count: number;
  outcome_record_count: number;
  dataset_sha256: string;
  source_code_sha256: string;
  evaluation_scope: string;
  price_scope: string;
  benchmarks: ForecastBenchmark[];
};

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid benchmark');
  return value as Record<string, unknown>;
}

function count(value: unknown) {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new Error('Invalid benchmark');
  return value as number;
}

function metric(value: unknown, minimum = 0, maximum = Number.POSITIVE_INFINITY) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error('Invalid benchmark');
  }
  return value;
}

function text(value: unknown, pattern: RegExp, maximum = 256) {
  if (typeof value !== 'string' || value.length > maximum || !pattern.test(value)) throw new Error('Invalid benchmark');
  return value;
}

function interval(value: unknown, minimum: number, maximum: number): [number, number] {
  if (!Array.isArray(value) || value.length !== 2) throw new Error('Invalid benchmark');
  const lower = metric(value[0], minimum, maximum);
  const upper = metric(value[1], minimum, maximum);
  if (lower > upper) throw new Error('Invalid benchmark');
  return [lower, upper];
}

export function publicForecastBenchmark(value: unknown): ForecastBenchmarkBundle {
  const data = object(value);
  if (data.schema_version !== 1 || data.sport !== 'nfl' || !Array.isArray(data.benchmarks)
      || data.benchmarks.length < 1 || data.benchmarks.length > 8) throw new Error('Invalid benchmark');
  const benchmarks = data.benchmarks.map(raw => {
    const item = object(raw);
    const prop = text(item.prop_type, /^(pass_yds|receptions)$/) as ForecastBenchmark['prop_type'];
    const candidateCount = count(item.candidate_count);
    const evaluatedCount = count(item.evaluated_count);
    const missing = count(item.missing_or_small_sample);
    const unknown = count(item.unknown_or_ambiguous_player);
    const calibrationCount = count(item.calibration_count);
    const positiveCount = count(item.calibration_positive_count);
    const baseline = metric(item.baseline_50_brier, 0, 1);
    const brier = metric(item.brier_score, 0, 1);
    const logLoss = metric(item.log_loss);
    const calibrationError = metric(item.calibration_error, 0, 1);
    const brierInterval = interval(item.brier_score_game_cluster_interval, 0, 1);
    const logLossInterval = interval(item.log_loss_game_cluster_interval, 0, Number.POSITIVE_INFINITY);
    const gameClusterCount = count(item.game_cluster_count);
    if (evaluatedCount + missing + unknown !== candidateCount || calibrationCount !== evaluatedCount
        || positiveCount > calibrationCount || gameClusterCount > calibrationCount
        || brier < brierInterval[0] || brier > brierInterval[1]
        || logLoss < logLossInterval[0] || logLoss > logLossInterval[1]) {
      throw new Error('Invalid benchmark');
    }
    return {prop_type:prop, label:text(item.label, /^[A-Za-z ]{1,40}$/),
      research_threshold:metric(item.research_threshold), candidate_count:candidateCount,
      evaluated_count:evaluatedCount, missing_or_small_sample:missing,
      unknown_or_ambiguous_player:unknown, calibration_count:calibrationCount,
      calibration_positive_count:positiveCount, brier_score:brier, log_loss:logLoss,
      calibration_error:calibrationError, baseline_50_brier:baseline,
      game_cluster_count:gameClusterCount,
      brier_score_game_cluster_interval:brierInterval,
      log_loss_game_cluster_interval:logLossInterval};
  });
  if (new Set(benchmarks.map(item => item.prop_type)).size !== benchmarks.length) throw new Error('Invalid benchmark');
  return {schema_version:1, id:text(data.id, /^[a-z0-9-]{1,64}$/), sport:'nfl',
    title:text(data.title, /^[A-Za-z0-9 ]{1,80}$/),
    start_date:text(data.start_date, /^\d{4}-\d{2}-\d{2}$/),
    end_date:text(data.end_date, /^\d{4}-\d{2}-\d{2}$/),
    retrieved_at:text(data.retrieved_at, /^\d{4}-\d{2}-\d{2}T/, 64),
    model_version:text(data.model_version, /^[A-Za-z0-9._-]{1,64}$/),
    game_count:count(data.game_count), outcome_record_count:count(data.outcome_record_count),
    dataset_sha256:text(data.dataset_sha256, /^[a-f0-9]{64}$/),
    source_code_sha256:text(data.source_code_sha256, /^[a-f0-9]{64}$/),
    evaluation_scope:text(data.evaluation_scope, /^.{1,500}$/, 500),
    price_scope:text(data.price_scope, /^.{1,500}$/, 500), benchmarks};
}

export function forecastChecks(benchmark: ForecastBenchmark) {
  return {
    brier: benchmark.brier_score_game_cluster_interval[1] < benchmark.baseline_50_brier,
    log_loss: benchmark.log_loss_game_cluster_interval[1] < Math.log(2),
    calibration: benchmark.calibration_error <= 0.05,
  };
}
