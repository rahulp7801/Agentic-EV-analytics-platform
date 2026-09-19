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

export type ForecastEvidenceRecord = {
  id: string;
  event_id: string;
  player_name: string;
  prop_type: ForecastBenchmark['prop_type'];
  actual_value: number;
  game_start_time: string;
  game_date: string;
  team: string;
  opponent: string;
  source_url: string;
  source_sha256: string;
  research_threshold: number;
  model_probability: number;
  sample_size: number;
  outcome: boolean;
};

export type ForecastBenchmarkBundle = {
  schema_version: 2;
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
  records: ForecastEvidenceRecord[];
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

function timestamp(value: unknown) {
  const result = text(value, /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/, 64);
  if (!Number.isFinite(Date.parse(result))) throw new Error('Invalid benchmark');
  return result;
}

function sourceUrl(value: unknown, eventId: string) {
  const result = text(value, /^https:\/\/site\.api\.espn\.com\//, 300);
  const parsed = new URL(result);
  if (parsed.origin !== 'https://site.api.espn.com'
      || parsed.pathname !== '/apis/site/v2/sports/football/nfl/summary'
      || parsed.searchParams.size !== 1 || parsed.searchParams.get('event') !== eventId) {
    throw new Error('Invalid benchmark');
  }
  return result;
}

export function publicForecastBenchmark(value: unknown): ForecastBenchmarkBundle {
  const data = object(value);
  if (data.schema_version !== 2 || data.sport !== 'nfl' || !Array.isArray(data.benchmarks)
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
  const startDate=text(data.start_date, /^\d{4}-\d{2}-\d{2}$/);
  const endDate=text(data.end_date, /^\d{4}-\d{2}-\d{2}$/);
  const gameCount=count(data.game_count);
  if (startDate>endDate) throw new Error('Invalid benchmark');
  if (!Array.isArray(data.records) || data.records.length < 1 || data.records.length > 1000
      || data.records.length !== benchmarks.reduce((total,item)=>total+item.evaluated_count,0)) {
    throw new Error('Invalid benchmark');
  }
  const thresholdByProp=new Map(benchmarks.map(item=>[item.prop_type,item.research_threshold]));
  const records=data.records.map(raw=>{
    const item=object(raw);
    const eventId=text(item.event_id,/^\d{6,12}$/);
    const prop=text(item.prop_type,/^(pass_yds|receptions)$/) as ForecastEvidenceRecord['prop_type'];
    const threshold=metric(item.research_threshold,0,10000);
    const actual=metric(item.actual_value,0,10000);
    if (thresholdByProp.get(prop)!==threshold || typeof item.outcome!=='boolean'
        || item.outcome!==(actual>threshold)) throw new Error('Invalid benchmark');
    const gameDate=text(item.game_date,/^\d{4}-\d{2}-\d{2}$/);
    if (gameDate < startDate || gameDate > endDate) throw new Error('Invalid benchmark');
    return {id:text(item.id,/^\d{6,12}-(pass_yds|receptions)-\d{1,16}$/,128),event_id:eventId,
      player_name:text(item.player_name,/^[A-Za-z.' -]{1,100}$/),prop_type:prop,
      actual_value:actual,game_start_time:timestamp(item.game_start_time),game_date:gameDate,
      team:text(item.team,/^[A-Z0-9]{2,4}$/),opponent:text(item.opponent,/^[A-Z0-9]{2,4}$/),
      source_url:sourceUrl(item.source_url,eventId),
      source_sha256:text(item.source_sha256,/^[a-f0-9]{64}$/),research_threshold:threshold,
      model_probability:metric(item.model_probability,0,1),sample_size:count(item.sample_size),
      outcome:item.outcome};
  });
  if (new Set(records.map(item=>item.id)).size!==records.length) throw new Error('Invalid benchmark');
  for (const benchmark of benchmarks) {
    if (records.filter(item=>item.prop_type===benchmark.prop_type).length!==benchmark.evaluated_count) {
      throw new Error('Invalid benchmark');
    }
  }
  if (new Set(records.map(item=>item.event_id)).size!==gameCount) throw new Error('Invalid benchmark');
  return {schema_version:2, id:text(data.id, /^[a-z0-9-]{1,64}$/), sport:'nfl',
    title:text(data.title, /^[A-Za-z0-9 ]{1,80}$/),
    start_date:startDate, end_date:endDate,
    retrieved_at:text(data.retrieved_at, /^\d{4}-\d{2}-\d{2}T/, 64),
    model_version:text(data.model_version, /^[A-Za-z0-9._-]{1,64}$/),
    game_count:gameCount, outcome_record_count:count(data.outcome_record_count),
    dataset_sha256:text(data.dataset_sha256, /^[a-f0-9]{64}$/),
    source_code_sha256:text(data.source_code_sha256, /^[a-f0-9]{64}$/),
    evaluation_scope:text(data.evaluation_scope, /^.{1,500}$/, 500),
    price_scope:text(data.price_scope, /^.{1,500}$/, 500), benchmarks,records};
}

export function forecastResult(record: ForecastEvidenceRecord) {
  const side=record.model_probability>=0.5 ? 'over' : 'under';
  return {side,correct:(side==='over')===record.outcome};
}

/** Fixed descriptive tier: at least 60% probability on the called direction. */
export function highestConvictionForecast(record: ForecastEvidenceRecord) {
  return Math.abs(record.model_probability - 0.5) >= 0.1 - Number.EPSILON;
}

export function forecastCohort(records: ForecastEvidenceRecord[]) {
  const correct=records.filter(record=>forecastResult(record).correct).length;
  const sample=records.length;
  if (!sample) return {sample:0,correct:0,hit_rate:null,wilson_interval:null,
    game_count:0,game_cluster_rate:null,game_cluster_interval:null};
  const hitRate=correct/sample,z=1.959963984540054,denominator=1+z*z/sample;
  const center=(hitRate+z*z/(2*sample))/denominator;
  const radius=z*Math.sqrt(hitRate*(1-hitRate)/sample+z*z/(4*sample*sample))/denominator;
  const groups=new Map<string,ForecastEvidenceRecord[]>();
  for (const record of records) groups.set(record.event_id,[...(groups.get(record.event_id) ?? []),record]);
  const gameRates=[...groups.values()].map(group=>
    group.filter(record=>forecastResult(record).correct).length/group.length);
  const gameRate=gameRates.reduce((total,value)=>total+value,0)/gameRates.length;
  let gameInterval:[number,number]|null=null;
  if (gameRates.length>=2) {
    const variance=gameRates.reduce((total,value)=>total+(value-gameRate)**2,0)/(gameRates.length-1);
    const critical=gameRates.length<=10 ? 2.262 : gameRates.length<=15 ? 2.145
      : gameRates.length<=20 ? 2.093 : gameRates.length<=30 ? 2.045 : 1.96;
    const gameRadius=critical*Math.sqrt(variance/gameRates.length);
    gameInterval=[Math.max(0,gameRate-gameRadius),Math.min(1,gameRate+gameRadius)];
  }
  return {sample,correct,hit_rate:hitRate,wilson_interval:[center-radius,center+radius] as [number,number],
    game_count:gameRates.length,game_cluster_rate:gameRate,game_cluster_interval:gameInterval};
}

/** Evidence display gate. This never admits a wager or substitutes for priced validation. */
export function forecastEvidenceGate(stats: ReturnType<typeof forecastCohort>, minimumRate=0.65,
  minimumSample=100, minimumGames=10) {
  return stats.sample>=minimumSample && stats.game_count>=minimumGames
    && stats.game_cluster_interval!==null && stats.game_cluster_interval[0]>=minimumRate;
}

export function forecastChecks(benchmark: ForecastBenchmark) {
  return {
    brier: benchmark.brier_score_game_cluster_interval[1] < benchmark.baseline_50_brier,
    log_loss: benchmark.log_loss_game_cluster_interval[1] < Math.log(2),
    calibration: benchmark.calibration_error <= 0.05,
  };
}
