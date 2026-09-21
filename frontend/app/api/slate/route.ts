import {liveSchedule} from '../../../lib/liveSchedule.ts';
import {scheduleSnapshot} from '../../../lib/scheduleStatus.ts';
import {slateReadiness,settlementProgress} from '../../../lib/slateReadiness.ts';
import {NO_STORE_HEADERS,PUBLIC_CACHE_HEADERS} from '../../../lib/publicCache.ts';
export const dynamic='force-dynamic';
export async function GET(request:Request) {
  const sport=new URL(request.url).searchParams.get('sport') ?? 'nfl';
  if(sport!=='nba' && sport!=='nfl' && sport!=='cfb') return Response.json({error:'Unsupported sport.'},{status:400,headers:NO_STORE_HEADERS});
  const now=Date.now();
  let result:ReturnType<typeof scheduleSnapshot>|null=null;
  let scan:Record<string,unknown>|null=null,reports:unknown[]=[],coverage_available=false;
  try {
    const {snapshots}=await import('@/lib/database');
    const values=await snapshots(['slate:'+sport,'scan:'+sport,'pipeline:daily','pipeline:public_daily']);
    scan=values['scan:'+sport];reports=[values['pipeline:daily'],values['pipeline:public_daily']];coverage_available=true;
    const captured=scheduleSnapshot(values['slate:'+sport],sport,now,6);
    if(captured.status===200) result=captured;
  } catch { /* Provider-backed fixtures remain visible when worker metadata is unavailable. */ }
  // CFB is populated by the serialized worker. Avoid a seven-request ESPN burst
  // from every page view when the stored slate is absent or stale.
  result ??=sport==='cfb' ? scheduleSnapshot(null,sport,now,6) : await liveSchedule(sport,now,6);
  if(result.status!==200) return Response.json(result.body,{status:503,headers:NO_STORE_HEADERS});
  const games=slateReadiness(result.body.games,scan,now);
  return Response.json({...result.body,games,coverage_available,
    settlements:settlementProgress(reports,sport,now),window_days:7},{headers:PUBLIC_CACHE_HEADERS.status});
}
