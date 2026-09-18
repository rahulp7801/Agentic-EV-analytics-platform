import {liveSchedule} from '../../../lib/liveSchedule.ts';
import {slateReadiness,settlementProgress} from '../../../lib/slateReadiness.ts';
export const dynamic='force-dynamic';
export async function GET(request:Request) {
  const sport=new URL(request.url).searchParams.get('sport') ?? 'nfl';
  if(sport!=='nba' && sport!=='nfl') return Response.json({error:'Unsupported sport.'},{status:400});
  const now=Date.now();
  const schedule=liveSchedule(sport,now,6);
  let scan:Record<string,unknown>|null=null,reports:unknown[]=[],coverage_available=false;
  try {
    const {snapshots}=await import('@/lib/database');
    const values=await snapshots(['scan:'+sport,'pipeline:daily','pipeline:public_daily']);
    scan=values['scan:'+sport];reports=[values['pipeline:daily'],values['pipeline:public_daily']];coverage_available=true;
  } catch { /* Provider-backed fixtures remain visible when worker metadata is unavailable. */ }
  const result=await schedule;
  if(result.status!==200) return Response.json(result.body,{status:503,headers:{'Cache-Control':'no-store'}});
  return Response.json({...result.body,games:slateReadiness(result.body.games,scan,now),coverage_available,
    settlements:settlementProgress(reports,sport,now),window_days:7},{headers:{'Cache-Control':'no-store'}});
}
