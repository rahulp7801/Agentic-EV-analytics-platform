import { database } from '@/lib/database';
import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const sport = params.get('sport') ?? 'nba';
  const player = (params.get('player') ?? '').trim();
  const limitText = params.get('limit') ?? '40';
  if (!['nba','nfl'].includes(sport) || player.length>100 || !/^\d+$/.test(limitText) || Number(limitText)<1) {
    return NextResponse.json({error:'Invalid game-log request'}, {status:400});
  }
  const limit = Math.min(Number(limitText),200);
  try {
    const {rows} = await database().query(
      'SELECT payload FROM dashboard_gamelogs WHERE sport=$1 AND ($2=\'\' OR strpos(lower(player_name),lower($2))>0) '
      + 'ORDER BY game_date DESC,player_name,game_key LIMIT $3', [sport,player,limit]);
    return NextResponse.json({logs:rows.map(row=>row.payload)}, {headers:{'Cache-Control':'no-store'}});
  } catch {
    return NextResponse.json({error:'Game logs are temporarily unavailable.',logs:[]}, {status:503});
  }
}
