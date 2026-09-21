import {publicPickBoard} from '../../../lib/pickBoard.ts';
import type {Sport} from '../../../lib/types.ts';

export const dynamic='force-dynamic';

export async function GET(request:Request) {
  const sport=new URL(request.url).searchParams.get('sport');
  if(!['nfl','nba','cfb'].includes(String(sport))) return Response.json({error:'Unsupported sport.'},
    {status:400,headers:{'Cache-Control':'no-store'}});
  try {
    const {snapshots}=await import('@/lib/database');
    const keys=[`picks:${sport}`,`player-profiles:${sport}`];
    const data=await snapshots(keys);
    return Response.json(publicPickBoard(data[keys[0]],data[keys[1]],sport as Sport),
      {headers:{'Cache-Control':'no-store','Vercel-CDN-Cache-Control':'public, s-maxage=10'}});
  } catch {
    return Response.json({error:'The pregame pick board is temporarily unavailable.'},{status:503,headers:{'Cache-Control':'no-store'}});
  }
}
