import {NextResponse} from 'next/server';
import {snapshots} from '@/lib/database';
import {publicPickBoard} from '@/lib/pickBoard';
import type {Sport} from '@/lib/types';

export const dynamic='force-dynamic';

export async function GET(request:Request) {
  const sport=new URL(request.url).searchParams.get('sport');
  if(!['nfl','nba','cfb'].includes(String(sport))) return NextResponse.json({error:'Unsupported sport.'},{status:400});
  try {
    const keys=[`picks:${sport}`,`player-profiles:${sport}`];
    const data=await snapshots(keys);
    return NextResponse.json(publicPickBoard(data[keys[0]],data[keys[1]],sport as Sport),
      {headers:{'Cache-Control':'no-store','Vercel-CDN-Cache-Control':'public, s-maxage=10'}});
  } catch {
    return NextResponse.json({error:'The pregame pick board is temporarily unavailable.'},{status:503,headers:{'Cache-Control':'no-store'}});
  }
}
