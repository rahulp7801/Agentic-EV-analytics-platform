import {liveSchedule} from '../../../lib/liveSchedule.ts';
import {NO_STORE_HEADERS,PUBLIC_CACHE_HEADERS} from '../../../lib/publicCache.ts';

export async function GET(request:Request) {
  const sport=new URL(request.url).searchParams.get('sport') ?? 'nba';
  if(sport!=='nba' && sport!=='nfl') return Response.json({error:'Invalid sport'},{status:400,headers:NO_STORE_HEADERS});
  if(process.env.VERCEL==='1') {
    try {
      const {snapshot}=await import('@/lib/database');
      const {scheduleSnapshot}=await import('@/lib/scheduleStatus');
      const result=scheduleSnapshot(await snapshot('schedule:'+sport),sport);
      if(result.status===200) return Response.json(result.body,{headers:PUBLIC_CACHE_HEADERS.status});
    } catch { /* Recover using the same bounded, free public feed. */ }
  }
  const result=await liveSchedule(sport);
  return Response.json(result.body,{status:result.status,
    headers:result.status===200 ? PUBLIC_CACHE_HEADERS.status : NO_STORE_HEADERS});
}
