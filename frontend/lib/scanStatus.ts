export function scanStatus(data: Record<string, unknown> | null, now = Date.now()) {
  if (!data) return {state:'not_run',label:'No scan recorded',updated_at:null,eligible:null,completed:null,deferred:null,quotes:null,selections:null,model_requests:null,model_estimates:null};
  const stamp=String(data.finished_at || data.started_at || '');
  const age=now-Date.parse(stamp);
  const count=(value:unknown)=>typeof value==='number' && Number.isInteger(value) && value>=0 ? value : null;
  const eligible=count(data.eligible_events), completed=count(data.completed_events), deferred=count(data.budget_skipped_events);
  const coverage=Object.values((data.coverage || {}) as Record<string,{quotes?:number;selections?:number;model_requests?:number;model_estimates?:number}>);
  const quotes=coverage.reduce((total,item)=>total+(count(item.quotes) || 0),0);
  const total=(field:'selections'|'model_requests'|'model_estimates')=>coverage.reduce((sum,item)=>sum+(count(item[field]) || 0),0);
  const selections=total('selections'), model_requests=total('model_requests'), model_estimates=total('model_estimates');
  let state='unknown',label='Scan status unavailable';
  if (Number.isFinite(age) && age>=-60000) {
    if (data.status==='running') {
      state=age>20*60000 ? 'interrupted' : 'running';
      label=state==='interrupted' ? 'Scan overdue' : 'Scanning';
    } else if (age>45*60000) {state='stale';label='Scan is stale';}
    else if (data.status==='blocked') {state='blocked';label='Waiting for refreshed history';}
    else if (data.status==='failed') {state='failed';label='Scan failed';}
    else if (Array.isArray(data.failures) && data.failures.length) {state='degraded';label='Scan had failures';}
    else if (data.status==='degraded') {state='degraded';label='Model coverage incomplete';}
    else if (deferred && deferred>0) {state='partial';label='Budget limited coverage';}
    else if (data.status==='complete' && eligible===0) {state='no_games';label='No games in next 24 hours';}
    else if (data.status==='complete' && completed && quotes===0) {state='no_quotes';label='No usable prop quotes';}
    else if (data.status==='complete' && completed===eligible && completed!==null) {state='complete';label='Scan complete';}
  }
  return {state,label,updated_at:Number.isFinite(Date.parse(stamp)) ? stamp : null,eligible,completed,deferred,quotes,selections,model_requests,model_estimates};
}
