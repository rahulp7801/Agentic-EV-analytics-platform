import {liveSchedule} from '../../../lib/liveSchedule.ts';
import {scheduleSnapshot} from '../../../lib/scheduleStatus.ts';
import {slateReadiness,settlementProgress} from '../../../lib/slateReadiness.ts';
export const dynamic='force-dynamic';
export async function GET(request:Request) {
  const sport=new URL(request.url).searchParams.get('sport') ?? 'nfl';
  if(sport!=='nba' && sport!=='nfl' && sport!=='cfb') return Response.json({error:'Unsupported sport.'},{status:400,headers:{'Cache-Control':'no-store'}});
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
  result ??=await liveSchedule(sport,now,6);
  if(result.status!==200) return Response.json(result.body,{status:503,headers:{'Cache-Control':'no-store'}});
  const games=sport==='cfb' ? result.body.games.filter(game=>Date.parse(game.game_time)>now && !game.completed)
    .map(game=>({...game,state:'Sportsbook market capture only'})) : slateReadiness(result.body.games,scan,now);
  return Response.json({...result.body,games,coverage_available,
    settlements:settlementProgress(reports,sport,now),window_days:7},{headers:{'Cache-Control':'no-store','Vercel-CDN-Cache-Control':'public, s-maxage=10'}});
}
