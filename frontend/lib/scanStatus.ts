const object=(value:unknown):value is Record<string,unknown>=>!!value && typeof value==='object' && !Array.isArray(value);
const count=(value:unknown):number|null=>typeof value==='number' && Number.isSafeInteger(value) && value>=0 ? value : null;
const timestamp=(value:unknown)=>typeof value==='string' && value.length<=64 && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && Number.isFinite(Date.parse(value));

export function scanStatus(value: unknown, now = Date.now()) {
  const empty={state:value==null ? 'not_run' : 'unknown',label:value==null ? 'No scan recorded' : 'Scan status unavailable',
    updated_at:null as string|null,next_refresh_at:null as string|null,overdue_at:null as string|null,
    eligible:null as number|null,completed:null as number|null,deferred:null as number|null,
    quotes:null as number|null,selections:null as number|null,model_requests:null as number|null,
    model_estimates:null as number|null,unresolved_selections:null as number|null,missing_estimates:null as number|null};
  if(!object(value)) return empty;
  const data=value,stamp=data.finished_at || data.started_at;
  const age=timestamp(stamp) ? now-Date.parse(stamp as string) : NaN;
  const eligible=count(data.eligible_events),completed=count(data.completed_events),deferred=count(data.budget_skipped_events);
  const raw=object(data.coverage) ? Object.values(data.coverage) : null;
  const coverage=raw && raw.length<=10000 && raw.every(object) ? raw : null;
  // Missing fields mean unknown coverage. Only explicit, valid counts can sum to zero.
  const total=(field:string):number|null=>{
    if(!coverage) return null;
    const values=coverage.map(item=>count(item[field]));
    if(values.some(item=>item===null)) return null;
    const sum=values.reduce<number>((sum,item)=>sum+item!,0);
    return Number.isSafeInteger(sum) ? sum : null;
  };
  const quotes=total('quotes'),selections=total('selections'),model_requests=total('model_requests'),model_estimates=total('model_estimates');
  const modelCountsValid=selections!==null && model_requests!==null && model_estimates!==null
    && model_requests<=selections && model_estimates<=model_requests
    && coverage!.every(item=>Number(item.model_requests)<=Number(item.selections) && Number(item.model_estimates)<=Number(item.model_requests));
  const unresolved_selections=modelCountsValid ? selections!-model_requests! : null;
  const missing_estimates=modelCountsValid ? model_requests!-model_estimates! : null;
  const next=timestamp(data.next_refresh_at) ? data.next_refresh_at as string : null;
  const nextTime=next ? Date.parse(next) : NaN;
  // A report can finish after a check became due during its bounded 20-minute run.
  const boundedDue=Number.isFinite(age) && nextTime>=Date.parse(stamp as string)-20*60000
    && nextTime<=Date.parse(stamp as string)+48*3600000;
  const overdue=data.status==='scheduled' && (count(data.cadence_deferred_events) ?? 0)>0 && boundedDue && nextTime<=now;
  let state='unknown',label='Scan status unavailable';
  if(Number.isFinite(age) && age>=-60000) {
    if(data.status==='running') {
      state=age>20*60000 ? 'interrupted' : 'running';
      label=state==='interrupted' ? 'Scan overdue' : 'Scanning';
    } else if(overdue) {state='overdue';label='Quote check overdue';}
    else if(age>45*60000) {state='stale';label='Scan is stale';}
    else if(data.status==='blocked') {state='blocked';label='Waiting for refreshed history';}
    else if(data.status==='failed') {state='failed';label='Scan failed';}
    else if(Array.isArray(data.failures) && data.failures.length) {state='degraded';label='Scan had failures';}
    else if(deferred && deferred>0) {state='partial';label=completed===0 ? 'Scan paused: API budget' : 'Coverage limited: API budget';}
    else if(data.status==='scheduled' && count(data.cadence_deferred_events)) {state='scheduled';label='Waiting for next quote check';}
    else if(data.status==='degraded') {
      state='degraded';label=unresolved_selections ? 'Player history coverage incomplete'
        : missing_estimates ? 'Model estimates incomplete' : 'Model coverage incomplete';
    } else if(!modelCountsValid || quotes===null || eligible===null || completed===null || completed>eligible
      || (completed>0 && !coverage?.length) || (data.status==='complete' && (unresolved_selections || missing_estimates))) {
      label='Scan coverage unavailable or invalid';
    } else if(data.status==='complete' && eligible===0 && completed===0) {state='no_games';label='No upcoming games in scan window';}
    else if(data.status==='complete' && completed>0 && quotes===0) {state='no_quotes';label='No usable prop quotes';}
    else if(data.status==='complete' && completed===eligible) {state='complete';label='Scan complete';}
  }
  return {state,label,updated_at:timestamp(stamp) ? stamp as string : null,
    next_refresh_at:state==='scheduled' && boundedDue && nextTime>now && nextTime<=now+48*3600000 ? next : null,
    overdue_at:state==='overdue' ? next : null,eligible,completed,deferred,quotes,selections,model_requests,
    model_estimates,unresolved_selections,missing_estimates};
}
