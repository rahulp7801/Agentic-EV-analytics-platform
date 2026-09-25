/** Server-only diagnostics: never emit an error, SQL, connection config or request value. */
export type DatabaseOperation='gamelogs'|'forecast_page'|'snapshot'|'snapshots'|'unspecified';
export type DatabasePhase='configure'|'connect'|'query'|'backpressure'|'close';
const OPERATIONS=new Set(['gamelogs','forecast_page','snapshot','snapshots']);
const PHASES=new Set(['configure','connect','query','backpressure','close']);
const CODES:Record<string,string>={
  '53300':'connection_limit','57014':'query_cancelled',
  '28P01':'authentication','28000':'authentication','42501':'permission',
  '42P01':'schema','42703':'schema','57P01':'database_unavailable',
  '57P02':'database_unavailable','57P03':'database_unavailable',
  'ECONNREFUSED':'connection_refused','ECONNRESET':'connection_reset',
  'ENOTFOUND':'dns','EAI_AGAIN':'dns','ETIMEDOUT':'network_timeout',
  'CERT_HAS_EXPIRED':'tls','SELF_SIGNED_CERT_IN_CHAIN':'tls',
  'DEPTH_ZERO_SELF_SIGNED_CERT':'tls','UNABLE_TO_VERIFY_LEAF_SIGNATURE':'tls',
};

function field(error:unknown,key:'code'|'message'):unknown {
  try {return error!==null && typeof error==='object' ? (error as Record<string,unknown>)[key] : undefined;}
  catch {return undefined;}
}
function category(error:unknown,phase:DatabasePhase):string {
  if(phase==='backpressure') return 'local_capacity';
  const code=field(error,'code');
  if(typeof code==='string' && Object.hasOwn(CODES,code)) return CODES[code];
  // Exact messages from the installed pg client; never log arbitrary message text.
  const message=field(error,'message');
  if(message==='Query read timeout') return 'query_timeout';
  if(message==='timeout expired' && phase==='connect') return 'connection_timeout';
  if(message==='Connection terminated' || message==='Connection terminated unexpectedly') return 'connection_terminated';
  return 'unknown';
}
export function databaseFailure(error:unknown,phase:DatabasePhase,operation:DatabaseOperation,elapsedMs:number,activeQueries:number) {
  return {
    event:'dashboard_database_failure',
    operation:OPERATIONS.has(operation) ? operation : 'unspecified',
    phase:PHASES.has(phase) ? phase : 'unknown',
    category:category(error,phase),
    elapsed_ms:Number.isFinite(elapsedMs) ? Math.max(0,Math.min(86_400_000,Math.round(elapsedMs))) : 0,
    active_queries:Number.isInteger(activeQueries) ? Math.max(0,Math.min(6,activeQueries)) : 0,
  };
}
export type DatabaseFailure=ReturnType<typeof databaseFailure>;
export type FailureObserver=(failure:DatabaseFailure)=>void;

export function reportDatabaseFailure(failure:DatabaseFailure):void {
  try {console.error(JSON.stringify(failure));} catch { /* Diagnostics cannot break error handling. */ }
}
export function reportGameLogValidationFailure():void {
  try {console.error(JSON.stringify({event:'dashboard_data_failure',operation:'gamelogs',category:'invalid_public_data'}));}
  catch { /* Keep the generic public failure response intact. */ }
}
