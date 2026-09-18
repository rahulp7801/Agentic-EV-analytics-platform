import { databaseQuery } from '@/lib/database';
import { gameLogRequest,publicGameLogs } from '@/lib/publicGameLogs';
import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  let query:ReturnType<typeof gameLogRequest>;
  try {query=gameLogRequest(new URL(request.url).searchParams);} catch {
    return NextResponse.json({error:'Invalid game-log request'}, {status:400});
  }
  const {sport,player,limit,before,exact}=query;
  try {
    const {rows} = await databaseQuery<{payload: unknown}>(
      'SELECT payload FROM dashboard_gamelogs WHERE sport=$1 '
      + 'AND ($2=\'\' OR CASE WHEN $5 THEN lower(player_name)=lower($2) ELSE strpos(lower(player_name),lower($2))>0 END) '
      + 'AND ($4::date IS NULL OR game_date<$4::date) '
      + 'ORDER BY game_date DESC,player_name,game_key LIMIT $3', [sport,player,limit,before,exact]);
    return NextResponse.json({logs:publicGameLogs(rows.map(row=>row.payload),sport)},
      {headers:{'Cache-Control':'no-store','Vercel-CDN-Cache-Control':'public, s-maxage=10'}});
  } catch {
    return NextResponse.json({error:'Game logs are temporarily unavailable.',logs:[]}, {status:503});
  }
}
