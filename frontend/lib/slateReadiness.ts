import type {Sport} from './types';
export type SlateGame={home_name:string;away_name:string;home_abbr:string;away_abbr:string;
  game_time:string;date:string;provider_event_id?:string;completed?:boolean};
const STATES:Record<string,string>={waiting_quotes:'Waiting for odds',scheduled:'Waiting for next quote check',
  api_budget:'API budget limited',evaluating:'Evaluating props',failed:'Evaluation failed',evaluated:'Evaluated'};
const GATES:Record<string,string>={unknown_or_ambiguous_player:'Player history identity not resolved',
  missing_model_estimate:'Model estimate unavailable',insufficient_sample:'Too few prior games',
  availability_unavailable:'Injury evidence unavailable',roster_unconfirmed:'Roster identity not confirmed',
  teammate_availability_unmodeled:'Teammate risk not modeled',player_availability_risk:'Player availability risk',
  edge_not_confident:'Uncertainty does not support the edge',no_positive_edge:'No supported positive edge',
  uncertainty_unavailable:'Uncertainty unavailable',edge_review_limit:'Edge exceeds the model-review ceiling',
  missing_matching_prop_quote:'No matching observed price',model_error:'Model evaluation failed',
  incompatible_prediction_target:'Forecast target does not match this market',synthetic_price:'Price is synthetic',
  correlated_exposure:'Correlated player exposure',daily_exposure_limit:'Daily research exposure limit',
  previously_reserved:'Already reserved in this research portfolio',stale_quote:'Expired quote',game_started:'Game already started'};
function count(value:unknown) {return Number.isSafeInteger(value) && Number(value)>=0 && Number(value)<=100000 ? Number(value) : null;}
function name(value:unknown) {return typeof value==='string' && value.length<=100 && value.trim() && !/[\u0000-\u001f]/.test(value);}
function stamp(value:unknown) {return typeof value==='string' && value.length<=64 && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));}

/** Join providers only by exact teams AND kickoff; missing matches never imply evaluation. */
export function slateReadiness(games:SlateGame[],scan:Record<string,unknown>|null,now=Date.now()) {
  const finished=scan?.finished_at ?? scan?.started_at;
  const scanFresh=stamp(finished) && now-Date.parse(finished as string)>=-60000 && now-Date.parse(finished as string)<=45*60000;
  const events=Array.isArray(scan?.events) && scan.events.length<=100 ? scan.events : [];
  return games.filter(game=>!game.completed).map(game=>{
    const started=Date.parse(game.game_time)<=now;
    const matches=events.filter(value=>value && typeof value==='object' && !Array.isArray(value)
      && name(value.home_team) && name(value.away_team) && stamp(value.game_start_time)
      && value.home_team===game.home_name && value.away_team===game.away_name
      && Date.parse(value.game_start_time)===Date.parse(game.game_time));
    const event=matches.length===1 ? matches[0] as Record<string,unknown> : null;
    let state=started ? 'Live · picks locked' : Date.parse(game.game_time)-now>48*3600000 ? 'Outside the 48-hour scan window' : 'Waiting for scan';
    if(!started && state==='Waiting for scan' && scanFresh && scan?.status==='blocked') state='Waiting for verified history';
    if(!started && state==='Waiting for scan' && scanFresh && scan?.status==='failed') state='Scan failed';
    if(!started && event && scanFresh) state=STATES[String(event.state)] ?? 'Coverage unavailable';
    else if(!started && event && !scanFresh) state='Scan evidence is stale';
    const coverage=event && scanFresh && scan?.coverage && typeof scan.coverage==='object'
      ? (scan.coverage as Record<string,unknown>)[String(event.game_id)] : null;
    const c=coverage && typeof coverage==='object' && !Array.isArray(coverage) ? coverage as Record<string,unknown> : {};
    const counts=c.counts && typeof c.counts==='object' && !Array.isArray(c.counts) ? c.counts as Record<string,unknown> : {};
    const selections=count(c.selections),requests=count(c.model_requests),estimates=count(c.model_estimates);
    const accepted=count(counts.accepted);
    const valid=selections!==null && requests!==null && estimates!==null && estimates<=requests && requests<=selections;
    if(!started && state==='Evaluated') state=c.model_status==='no_quotes' ? 'No usable prop quotes'
      : !valid ? 'Coverage unavailable' : estimates<selections ? 'Player/model coverage incomplete' : 'Evaluated';
    return {...game,state,locked:started,quotes:started ? null : count(c.quotes),selections:started ? null : selections,model_estimates:started ? null : valid ? estimates : null,
      unresolved_selections:valid ? selections-requests : null,
      accepted_at_capture:!started && valid && accepted!==null && accepted<=estimates ? accepted : null,
      reasons:started ? [] : Object.entries(GATES).flatMap(([key,label])=>count(counts[key]) ? [{label,count:count(counts[key])!}] : []),
      checked_at:stamp(finished) ? finished as string : null,
      next_refresh_at:event && stamp(event.next_refresh_at) && Date.parse(event.next_refresh_at as string)>now
        && Date.parse(event.next_refresh_at as string)<=now+48*3600000 ? event.next_refresh_at as string : null};
  }).sort((a,b)=>Date.parse(a.game_time)-Date.parse(b.game_time));
}

export function settlementProgress(reports:unknown[],sport:Sport,now=Date.now()) {
  const values=reports.filter(value=>value && typeof value==='object' && !Array.isArray(value)) as Array<Record<string,unknown>>;
  const latest=values.filter(value=>stamp(value.finished_at) && Date.parse(value.finished_at as string)<=now+60000
    && ['complete','degraded','blocked','failed'].includes(String(
      (value.settlements as Record<string,Record<string,unknown>>|undefined)?.[sport]?.status)))
    .sort((a,b)=>Date.parse(b.finished_at as string)-Date.parse(a.finished_at as string))[0];
  const result=(latest?.settlements as Record<string,Record<string,unknown>>|undefined)?.[sport];
  if(!result || !['complete','degraded','blocked','failed'].includes(String(result.status))) return null;
  const candidates=count(result.candidates),settled=count(result.settled),pending=count(result.pending);
  if(['complete','degraded'].includes(String(result.status)) && (candidates===null || settled===null
    || pending===null || settled>candidates || settled+pending!==candidates)) return null;
  const reasons:Record<string,string>={final_game_not_matched:'Final game not confirmed',
    stat_not_found_or_ambiguous:'Final player stat missing or ambiguous',stat_provenance_invalid:'Stat evidence failed validation',
    invalid_prediction_or_evidence:'Prediction identity or chronology failed validation'};
  const raw=result.reasons && typeof result.reasons==='object' ? result.reasons as Record<string,unknown> : {};
  return {checked_at:latest.finished_at as string,status:String(result.status),stale:now-Date.parse(latest.finished_at as string)>36*3600000,
    candidates,settled,pending,
    outside_schedule:count(result.outside_schedule),
    blocked:result.reason==='history_refresh_unavailable' ? 'Waiting for verified player-history refresh' : null,
    reasons:Object.entries(reasons).flatMap(([key,label])=>count(raw[key]) ? [{label,count:count(raw[key])!}] : [])};
}
