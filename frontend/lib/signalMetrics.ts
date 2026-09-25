import type {AvailabilityContextSplit,AvailabilityEvidence,EVSignal,ModelSport,NextGenMetric,NextGenStatsEvidence,PlayerProfile,PropType,Sport} from './types';

const CURRENT_MODEL_VERSION = 'empirical-jeffreys-v4';

/** Validate display metrics without inventing uncertainty or execution eligibility. */
export function expectedProfit(expectedReturn: unknown, stake: number): number | null {
  return typeof expectedReturn === 'number' && Number.isFinite(expectedReturn) && Number.isFinite(stake) && stake >= 0
    ? expectedReturn * stake : null;
}

export function signalMetrics(s: Record<string, unknown>, now = Date.now()) {
  const p = Number(s.true_prob), odds = Number(s.american_odds);
  const push = Number(s.push_probability ?? 0);
  const quoteTime = Date.parse(String(s.snapped_at ?? ''));
  const start = Date.parse(String(s.game_start_time ?? ''));
  const synthetic = String(s.sportsbook).toLowerCase() === 'prizepicks';
  const sample = Number(s.sample_size), kelly = Number(s.kelly_fraction);
  const valid = typeof s.true_prob === 'number' && typeof s.american_odds === 'number' && Number.isFinite(p) && p >= 0 && p <= 1 && Number.isFinite(push) && push >= 0 && p + push <= 1.000001
    && Number.isInteger(odds) && Math.abs(odds) >= 100 && (s.direction === 'over' || s.direction === 'under');
  const legacy = s.model_version !== CURRENT_MODEL_VERSION;
  const stale = !Number.isFinite(quoteTime) || now - quoteTime > 300000 || quoteTime > now + 60000;
  const missingStart = !Number.isFinite(start), started = Number.isFinite(start) && start <= now;
  const availability = s.availability as AvailabilityEvidence | undefined;
  const availabilityTime = Date.parse(availability?.captured_at ?? '');
  const availabilityReason = availability?.status !== 'observed' || !availability.roster_confirmed
    || !Array.isArray(availability.teammates) || !Number.isFinite(availabilityTime) || now-availabilityTime>3600000 || availabilityTime>now+60000
    ? 'availability_unavailable'
    : !['Active','Not listed on injury report'].includes(availability.subject_status) ? 'player_availability_risk'
    : availability.teammates.some(row=>{
      const status=row.status.trim().toLowerCase();
      return (row.relationship===undefined || row.relationship==='teammate')
        && ['out','inactive','doubtful'].includes(status);
    }) ? 'teammate_availability_unmodeled' : null;
  const b = odds < 0 ? 100 / -odds : odds / 100;
  const ci = s.confidence_interval;
  const interval = !legacy && Array.isArray(ci) && ci.length === 2 && ci.every(x => typeof x === 'number' && Number.isFinite(x))
    && ci[0] >= 0 && ci[0] <= ci[1] && ci[1] <= 1 ? ci : null;
  const breakEven = (1 - push) / (1 + b);
  const expectedReturn=p*b-(1-p-push);
  const cutoff=Number.isFinite(start) ? new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(start) : null;
  const reason = !valid ? 'invalid_metrics' : legacy ? 'legacy_model' : synthetic ? 'synthetic_price'
    : missingStart ? 'missing_or_started_game' : started ? 'game_started' : stale ? 'stale_quote'
    : (!Number.isFinite(sample) || sample < 20) ? 'insufficient_sample'
    : (!Number.isFinite(kelly) || kelly < 0 || kelly > 0.25) ? 'invalid_stake'
    : availabilityReason ? availabilityReason
    : s.gated!==false ? String(s.gate_reason ?? 'risk_gate')
    : s.forecast_cutoff!==cutoff ? 'missing_prediction_cutoff'
    : !interval || interval[0]>p || interval[1]<p || interval[1]>1-push+1e-12 ? 'uncertainty_unavailable'
    : expectedReturn<=0 ? 'no_positive_edge'
    : interval[0]<=breakEven ? 'edge_not_confident' : null;
  return {...s, implied_prob: valid && !synthetic ? breakEven : s.implied_prob,
    ev_pct: valid && !synthetic ? p - breakEven : s.ev_pct, expected_return: valid && !legacy && !synthetic ? p * b - (1 - p - push) : null,
    confidence_interval: interval, strength: 'unrated', gated: reason !== null, gate_reason: reason,
    kelly_fraction: reason ? 0 : s.kelly_fraction};
}

const SPORTS = new Set<ModelSport>(['nba','nfl','cfb']);
const PROPS = new Set<PropType>(['points','rebounds','assists','threes','pra','steals','blocks',
  'pass_yds','pass_tds','rush_yds','rec_yds','receptions']);
const NFL_PROPS=new Set<PropType>(['pass_yds','pass_tds','rush_yds','rec_yds','receptions']);

function finite(value:unknown):value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function bounded(value:unknown, maximum:number, allowEmpty=false):value is string {
  return typeof value === 'string' && value.length<=maximum && !/[\u0000-\u001f]/.test(value)
    && (allowEmpty || Boolean(value.trim()));
}

function timestamp(value:unknown):value is string {
  return bounded(value,64) && /([zZ]|[+-]\d\d:\d\d)$/.test(value)
    && Number.isFinite(Date.parse(value));
}

function rosterSource(value:unknown,sport:Sport):value is string {
  if(!bounded(value,150)) return false;
  try {
    const url=new URL(value);
    const path=sport==='nfl' ? /^\/apis\/site\/v2\/sports\/football\/nfl\/teams\/[0-9]+\/roster$/
      : sport==='cfb' ? /^\/apis\/site\/v2\/sports\/football\/college-football\/teams\/[0-9]+\/roster$/
      : /^\/apis\/site\/v2\/sports\/basketball\/nba\/teams\/[0-9]+\/roster$/;
    return url.origin==='https://site.api.espn.com' && !url.username && !url.password
      && (!url.search || (sport==='cfb' && url.search==='?limit=1000')) && !url.hash && path.test(url.pathname);
  } catch {return false;}
}

function publicAvailability(value:unknown,sport:Sport,historyPlayerId?:unknown):AvailabilityEvidence|undefined {
  if (!value || typeof value!=='object' || Array.isArray(value)) return undefined;
  const a=value as Record<string,unknown>;
  if(a.status==='unavailable') return {status:'unavailable',roster_confirmed:false,
    subject_status:'Unknown',teammates:[],probability_adjusted:false};
  const url=sport==='nfl' ? 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries'
    : sport==='cfb' ? 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries'
    : 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries';
  if(a.status!=='observed' || a.roster_confirmed!==true || a.probability_adjusted!==false
    || !timestamp(a.captured_at)
    || !(a.source_url===url || (a.source_url===a.roster_source_url && a.source_sha256===a.roster_source_sha256))
    || !bounded(a.source_sha256,64)
    || !/^[a-f0-9]{64}$/.test(a.source_sha256) || !bounded(a.roster_source_sha256,64)
    || !/^[a-f0-9]{64}$/.test(a.roster_source_sha256) || !rosterSource(a.roster_source_url,sport)
    || !bounded(a.subject_status,100)
    || !bounded(a.team,5) || !Array.isArray(a.teammates) || a.teammates.length>64) return undefined;
  const teammates:AvailabilityEvidence['teammates']=[];
  const contextSplits:NonNullable<AvailabilityEvidence['context_splits']>=[];
  const identityFields=['roster_player_name','identity_source_url','identity_source_sha256'];
  const identified=identityFields.some(key=>a[key]!==undefined);
  const validIdentity=sport==='nfl'
    ? a.identity_source_url==='https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'
    : sport==='cfb' && a.identity_source_url===a.roster_source_url
      && a.identity_source_sha256===a.roster_source_sha256
      && bounded(a.player_id,20) && /^[1-9][0-9]*$/.test(a.player_id) && a.player_id===historyPlayerId;
  if(identified && (!validIdentity || !bounded(a.roster_player_name,100)
    || !bounded(a.identity_source_sha256,64) || !/^[a-f0-9]{64}$/.test(a.identity_source_sha256)))return undefined;
  for(const value of a.teammates) {
    if(!value || typeof value!=='object' || Array.isArray(value)) return undefined;
    const row=value as Record<string,unknown>;
    if(!bounded(row.player,100) || !bounded(row.status,100) || !bounded(row.position,10)
      || !timestamp(row.reported_at) || Date.parse(row.reported_at)>Date.parse(a.captured_at)+60000) return undefined;
    const contextFields=[row.team,row.relationship,row.unit,row.source_url,row.source_sha256];
    const hasContext=contextFields.some(item=>item!==undefined);
    if(hasContext && (!bounded(row.team,5) || !['teammate','opponent'].includes(String(row.relationship))
      || !['offense','defense'].includes(String(row.unit))
      || !(row.source_url===url || rosterSource(row.source_url,sport))
      || !bounded(row.source_sha256,64) || !/^[a-f0-9]{64}$/.test(row.source_sha256))) return undefined;
    teammates.push({player:row.player,status:row.status,position:row.position,reported_at:row.reported_at,
      ...(hasContext ? {team:row.team as string,relationship:row.relationship as 'teammate'|'opponent',
        unit:row.unit as 'offense'|'defense',source_url:row.source_url as string,
        source_sha256:row.source_sha256 as string} : {})});
  }
  if(a.context_splits!==undefined) {
    if(sport==='cfb') return undefined;
    if(!Array.isArray(a.context_splits) || a.context_splits.length>8) return undefined;
    for(const value of a.context_splits) {
      if(!value || typeof value!=='object' || Array.isArray(value)) return undefined;
      const row=value as Record<string,unknown>;
      // Older snapshots inferred absence from missing rows. Keep their current
      // injury report, but do not publish those descriptive cohorts.
      if(row.evidence_version===undefined) continue;
      const active=row.active as Record<string,unknown>|undefined;
      const absent=row.absent as Record<string,unknown>|undefined;
      const cohort=(item:Record<string,unknown>|undefined)=>!!item
        && typeof item.games==='number' && Number.isSafeInteger(item.games) && item.games>=0 && item.games<=40
        && (item.mean===null || (finite(item.mean) && Math.abs(Number(item.mean))<=10000))
        && (item.hit_rate===null || (finite(item.hit_rate) && Number(item.hit_rate)>=0 && Number(item.hit_rate)<=1))
        && (item.games===0 ? item.mean===null && item.hit_rate===null : finite(item.mean) && finite(item.hit_rate));
      const source=sport==='nfl' ? 'nflverse_snap_counts' : 'nba_final_box_scores';
      const participation=sport==='nfl' ? 'recorded unit snaps' : 'recorded minutes';
      if(!bounded(row.player,100) || !bounded(row.status,100) || !bounded(row.position,10)
        || !bounded(row.team,5) || !['teammate','opponent'].includes(String(row.relationship))
        || !['offense','defense'].includes(String(row.unit)) || row.source!==source
        || row.evidence_version!=='recorded-participation-v2'
        || typeof row.unknown_games!=='number' || !Number.isSafeInteger(row.unknown_games) || row.unknown_games<0
        || row.participation!==participation || !cohort(active) || !cohort(absent)
        || Number(active!.games)+Number(absent!.games)+row.unknown_games<1
        || Number(active!.games)+Number(absent!.games)+row.unknown_games>40
        || (sport==='nfl' && absent!.games!==0)) return undefined;
      contextSplits.push({player:row.player,status:row.status,position:row.position,team:row.team,
        relationship:row.relationship as 'teammate'|'opponent',unit:row.unit as 'offense'|'defense',
        source,participation,evidence_version:'recorded-participation-v2',unknown_games:row.unknown_games,active:active as AvailabilityContextSplit['active'],
        absent:absent as AvailabilityContextSplit['absent']});
    }
  }
  return {status:'observed',roster_confirmed:true,subject_status:a.subject_status,
    captured_at:a.captured_at,source_url:a.source_url as string,source_sha256:a.source_sha256,team:a.team,
    roster_source_url:a.roster_source_url,roster_source_sha256:a.roster_source_sha256,
    ...(bounded(a.player_id,20) && /^[0-9]+$/.test(a.player_id)
      && a.player_image_url===`https://a.espncdn.com/i/headshots/${sport==='cfb'?'college-football':sport}/players/full/${a.player_id}.png`
      ? {player_id:a.player_id,player_image_url:a.player_image_url} : {}),
    ...(identified ? {roster_player_name:a.roster_player_name as string,
      identity_source_url:a.identity_source_url as string,
      identity_source_sha256:a.identity_source_sha256 as string} : {}),
    teammates,...(contextSplits.length ? {context_splits:contextSplits} : {}),probability_adjusted:false};
}

function publicNextGenStats(value:unknown,sport:Sport,prop:PropType):NextGenStatsEvidence|undefined {
  if(sport!=='nfl' || !value || typeof value!=='object' || Array.isArray(value)) return undefined;
  const evidence=value as Record<string,unknown>;
  const expected:Partial<Record<PropType,NextGenStatsEvidence['stat_type']>>={
    pass_yds:'passing',pass_tds:'passing',rush_yds:'rushing',rec_yds:'receiving',receptions:'receiving'};
  const statType=expected[prop];
  const columns:Record<NextGenStatsEvidence['stat_type'],Set<NextGenMetric>>={
    passing:new Set(['avg_time_to_throw','avg_completed_air_yards','avg_intended_air_yards','aggressiveness']),
    receiving:new Set(['avg_separation','avg_cushion','avg_yac_above_expectation']),
    rushing:new Set(['efficiency','percent_attempts_gte_eight_defenders','rush_yards_over_expected','avg_time_to_los']),
  };
  const metrics=evidence.metrics;
  if(!statType || evidence.status!=='observed' || evidence.stat_type!==statType
    || evidence.source_provider!=='nflverse_ngs' || evidence.probability_adjusted!==false
    || evidence.cutoff_exclusive!==true || !Number.isSafeInteger(evidence.sample_weeks)
    || Number(evidence.sample_weeks)<1 || Number(evidence.sample_weeks)>8
    || !Number.isSafeInteger(evidence.cutoff_season) || Number(evidence.cutoff_season)<2016
    || Number(evidence.cutoff_season)>2100 || !Number.isSafeInteger(evidence.cutoff_week)
    || Number(evidence.cutoff_week)<1 || Number(evidence.cutoff_week)>22
    || evidence.source_url!==`https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_${statType}.parquet`
    || !bounded(evidence.source_sha256,64) || !/^[a-f0-9]{64}$/.test(evidence.source_sha256)
    || !timestamp(evidence.source_observed_at) || !metrics || typeof metrics!=='object'
    || Array.isArray(metrics)) return undefined;
  const entries=Object.entries(metrics);
  if(!entries.length || entries.some(([key,item])=>!columns[statType].has(key as NextGenMetric)
    || !finite(item) || Math.abs(item)>10000)) return undefined;
  return {status:'observed',stat_type:statType,sample_weeks:evidence.sample_weeks as number,
    cutoff_season:evidence.cutoff_season as number,cutoff_week:evidence.cutoff_week as number,
    cutoff_exclusive:true,metrics:{...metrics} as Partial<Record<NextGenMetric,number>>,
    source_provider:'nflverse_ngs',source_url:evidence.source_url,
    source_sha256:evidence.source_sha256,source_observed_at:evidence.source_observed_at,
    probability_adjusted:false};
}

/** Current identity metadata never supplies historical availability or eligibility. */
export function publicPlayerProfile(value:unknown,sport:Sport,player:string,now=Date.now()):PlayerProfile|undefined {
  if(!value || typeof value!=='object' || Array.isArray(value)) return undefined;
  const p=value as Record<string,unknown>;
  if(p.player!==player || !bounded(p.name,100) || !bounded(p.team,5)
    || !bounded(p.player_id,20) || !/^[1-9][0-9]*$/.test(p.player_id)
    || p.image_url!==`https://a.espncdn.com/i/headshots/${sport==='cfb'?'college-football':sport}/players/full/${p.player_id}.png`
    || !timestamp(p.captured_at) || Date.parse(p.captured_at)>now+60000
    || now-Date.parse(p.captured_at)>14*86400000 || !rosterSource(p.source_url,sport)
    || !bounded(p.source_sha256,64) || !/^[a-f0-9]{64}$/.test(p.source_sha256)) return undefined;
  const alias=p.name!==player;
  if(alias && (sport!=='nfl' || p.identity_source_url!=='https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'
    || !bounded(p.identity_source_sha256,64) || !/^[a-f0-9]{64}$/.test(p.identity_source_sha256))) return undefined;
  return {player,name:p.name,team:p.team,player_id:p.player_id,image_url:p.image_url,captured_at:p.captured_at,
    source_url:p.source_url,source_sha256:p.source_sha256,
    ...(bounded(p.jersey,2) && /^[0-9]{1,2}$/.test(p.jersey) ? {jersey:p.jersey} : {}),
    ...(bounded(p.position,10) && /^[A-Z0-9/-]+$/.test(p.position) ? {position:p.position} : {}),
    ...(alias ? {identity_source_url:p.identity_source_url as string,identity_source_sha256:p.identity_source_sha256 as string} : {})};
}

export function forecastWindow(signal:Pick<EVSignal,'game_start_time'>,now=Date.now()) {
  const start=Date.parse(signal.game_start_time ?? '');
  return Number.isFinite(start) && start>now ? 'upcoming' : 'archive';
}

export function latestForecastWindow(signals:EVSignal[],now=Date.now()) {
  return signals.some(signal=>forecastWindow(signal,now)==='upcoming') ? 'upcoming' : 'archive';
}

/** Return the only signal shape allowed across the public API boundary. */
export function publicSignal(value:unknown, now=Date.now()):EVSignal|null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const s=value as Record<string,unknown>;
  const sport=SPORTS.has(s.sport as ModelSport) ? s.sport as ModelSport : null;
  const prop=PROPS.has(s.prop_type as PropType) ? s.prop_type as PropType : null;
  const tradePlan=s.trade_plan;
  const flags=s.injury_flags;
  const mean=s.mean_stat;
  if (!bounded(s.id,128) || !bounded(s.player,100) || !bounded(s.team,20,true)
      || !bounded(s.opponent,20,true) || !bounded(s.home_team,100) || !bounded(s.away_team,100)
      || !bounded(s.game_id,128) || !sport || !prop || (sport==='nba' ? NFL_PROPS.has(prop) : !NFL_PROPS.has(prop))
      || !finite(s.line) || Number(s.line)<0 || Number(s.line)>10000
      || (s.direction !== 'over' && s.direction !== 'under')
      || !bounded(s.sportsbook,64) || s.sportsbook.toLowerCase()==='prizepicks'
      || typeof s.american_odds !== 'number' || !Number.isInteger(s.american_odds) || Math.abs(s.american_odds)<100
      || !finite(s.true_prob) || Number(s.true_prob)<0 || Number(s.true_prob)>1
      || !finite(s.push_probability) || Number(s.push_probability)<0
      || Number(s.true_prob)+Number(s.push_probability)>1.000001
      || typeof s.sample_size !== 'number' || !Number.isSafeInteger(s.sample_size)
      || s.sample_size<0 || s.sample_size>100000
      || (mean !== null && (!finite(mean) || Math.abs(mean)>10000)) || !bounded(s.model_version,64)
      || !timestamp(s.snapped_at) || !timestamp(s.game_start_time)
      || !Array.isArray(tradePlan) || tradePlan.length>3 || tradePlan.some(item=>!bounded(item,300,true))
      || !flags || typeof flags !== 'object' || Array.isArray(flags)
      || Object.entries(flags).length>20 || Object.entries(flags).some(
        ([key,item])=>!bounded(key,64) || !bounded(item,300,true))
      || !bounded(s.market_type,100)) return null;
  const availability=publicAvailability(s.availability,sport,s.player_id);
  const nextGenStats=publicNextGenStats(s.next_gen_stats,sport,prop);
  const playerProfile=publicPlayerProfile(s.player_profile,sport,s.player,now);
  const metrics=signalMetrics({...s,availability},now);
  if (!finite(metrics.implied_prob) || !finite(metrics.ev_pct)
      || (metrics.expected_return !== null && !finite(metrics.expected_return))) return null;
  const gateReason=typeof metrics.gate_reason === 'string' ? metrics.gate_reason : undefined;
  const interval=metrics.confidence_interval as [number,number]|null;
  return {id:s.id,player:s.player,team:s.team,opponent:s.opponent,home_team:s.home_team,
    away_team:s.away_team,sport,prop_type:prop,line:s.line as number,direction:s.direction,
    true_prob:s.true_prob,implied_prob:metrics.implied_prob as number,ev_pct:metrics.ev_pct as number,
    expected_return:metrics.expected_return as number|null,push_probability:s.push_probability,
    confidence_interval:interval,model_version:s.model_version,game_start_time:s.game_start_time,
    kelly_fraction:metrics.kelly_fraction as number,american_odds:s.american_odds,
    sportsbook:s.sportsbook,
    // Preserve stored forecasts, but withhold the obsolete generated claim of exact on/off evidence.
    trade_plan:tradePlan.filter(bullet=>!(bullet.startsWith('Availability: ')
      && bullet.includes(' exact historical on/off comparison'))),injury_flags:{...flags} as Record<string,string>,
    market_type:s.market_type,snapped_at:s.snapped_at,strength:'unrated',
    gated:metrics.gated as boolean,...(gateReason ? {gate_reason:gateReason} : {}),
    sample_size:s.sample_size,mean_stat:mean as number|null,game_id:s.game_id,
    ...(availability ? {availability} : {}),
    ...(nextGenStats ? {next_gen_stats:nextGenStats} : {}),
    ...(playerProfile ? {player_profile:playerProfile} : {}),
    ...(bounded(s.forecast_cutoff,10) && /^\d{4}-\d{2}-\d{2}$/.test(s.forecast_cutoff)
      && Number.isFinite(Date.parse(s.forecast_cutoff)) ? {forecast_cutoff:s.forecast_cutoff} : {})};
}

export function publicSignals(value:unknown, now=Date.now()) {
  if (!Array.isArray(value) || value.length>5000) throw new Error('Invalid signal collection');
  const signals:EVSignal[]=[];
  for (const item of value) {
    const signal=publicSignal(item,now);
    if (signal) signals.push(signal);
  }
  return {signals,invalid_signals:value.length-signals.length};
}

function publicGame(value:unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid signal game');
  const game=value as Record<string,unknown>;
  if (!bounded(game.game_id,128) || !bounded(game.home_team,100) || !bounded(game.away_team,100)
      || (game.sport!=='nfl' && game.sport!=='nba' && game.sport!=='cfb') || !bounded(game.date,8)
      || !/^\d{8}$/.test(game.date)) throw new Error('Invalid signal game');
  const calendar=`${game.date.slice(0,4)}-${game.date.slice(4,6)}-${game.date.slice(6,8)}`;
  const parsed=new Date(`${calendar}T00:00:00Z`);
  if (!Number.isFinite(parsed.valueOf()) || parsed.toISOString().slice(0,10)!==calendar)
    throw new Error('Invalid signal game');
  return {game_id:game.game_id,home_team:game.home_team,away_team:game.away_team,
    date:game.date,sport:game.sport as Sport};
}

/** Validate and project the complete stored signal snapshot boundary. */
export function publicSignalSnapshots(value:unknown, now=Date.now(), sport?:Sport) {
  if (!Array.isArray(value) || value.length>100) throw new Error('Invalid signal snapshots');
  const rawSignals:unknown[]=[];
  const games=new Map<string,ReturnType<typeof publicGame>>();
  let generatedAt:string|null=null;
  for (const item of value) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('Invalid signal snapshot');
    const snapshot=item as Record<string,unknown>;
    if (!timestamp(snapshot.generated_at)) throw new Error('Invalid signal snapshot');
    if (!generatedAt || Date.parse(snapshot.generated_at)>Date.parse(generatedAt)) generatedAt=snapshot.generated_at;
    const signals=snapshot.signals ?? [];
    const snapshotGames=snapshot.games ?? [];
    if (!Array.isArray(signals) || signals.length>500 || !Array.isArray(snapshotGames)
        || snapshotGames.length>10) throw new Error('Invalid signal snapshot');
    rawSignals.push(...signals);
    if (rawSignals.length>5000) throw new Error('Invalid signal snapshots');
    for (const value of snapshotGames) {
      const game=publicGame(value), key=`${game.sport}:${game.game_id}`;
      const previous=games.get(key);
      if (previous && JSON.stringify(previous)!==JSON.stringify(game)) throw new Error('Invalid signal game');
      games.set(key,game);
    }
  }
  const projected=publicSignals(rawSignals,now);
  return {generated_at:generatedAt,
    games:[...games.values()].filter(game=>!sport || game.sport===sport),
    ...projected,
    signals:projected.signals.filter(signal=>!sport || signal.sport===sport)};
}

export function parlayScenario(probabilities: number[], grossPayout: number) {
  if (probabilities.length < 2 || !Number.isFinite(grossPayout) || grossPayout <= 1
      || probabilities.some(p => !Number.isFinite(p) || p < 0 || p > 1)) return null;
  const independent = probabilities.reduce((a, p) => a * p, 1);
  const lower = Math.max(0, probabilities.reduce((a, p) => a + p, 0) - probabilities.length + 1);
  const upper = Math.min(...probabilities);
  return {independent, lower, upper, expectedReturn: independent * grossPayout - 1};
}
