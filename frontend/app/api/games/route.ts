import {liveSchedule} from '../../../lib/liveSchedule.ts';

export async function GET(request:Request) {
  const sport=new URL(request.url).searchParams.get('sport') ?? 'nba';
  if(sport!=='nba' && sport!=='nfl') return Response.json({error:'Invalid sport'},{status:400,headers:{'Cache-Control':'no-store'}});
  if(process.env.VERCEL==='1') {
    try {
      const {snapshot}=await import('@/lib/database');
      const {scheduleSnapshot}=await import('@/lib/scheduleStatus');
      const result=scheduleSnapshot(await snapshot('schedule:'+sport),sport);
      if(result.status===200) return Response.json(result.body,{headers:{'Cache-Control':'no-store','Vercel-CDN-Cache-Control':'public, s-maxage=10'}});
    } catch { /* Recover using the same bounded, free public feed. */ }
  }
  const result=await liveSchedule(sport);
  return Response.json(result.body,{status:result.status,headers:{'Cache-Control':'no-store',...(result.status===200 ? {'Vercel-CDN-Cache-Control':'public, s-maxage=10'} : {})}});
}
