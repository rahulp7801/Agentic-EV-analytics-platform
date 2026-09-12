import { snapshot } from '@/lib/database';
import { NextResponse } from 'next/server';
import { publicMarkets } from '@/lib/publicMarkets';
export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const sport = new URL(request.url).searchParams.get('sport');
  if (sport !== 'nfl' && sport !== 'nba') return NextResponse.json({error:'Invalid sport'}, {status:400});
  try {
    const data = await snapshot('markets:'+sport);
    if (!data) return NextResponse.json({error:'No market observations have been published yet.'}, {status:503});
    return NextResponse.json(publicMarkets(data,sport), {headers:{'Cache-Control':'no-store'}});
  } catch {
    return NextResponse.json({error:'Market observations are temporarily unavailable.'}, {status:503});
  }
}
