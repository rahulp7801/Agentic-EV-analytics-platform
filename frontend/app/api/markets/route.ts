import { snapshot } from '@/lib/database';
import { NextResponse } from 'next/server';
import { publicMarkets } from '@/lib/publicMarkets';
import {NO_STORE_HEADERS,PUBLIC_CACHE_HEADERS} from '@/lib/publicCache';
export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const sport = new URL(request.url).searchParams.get('sport');
  if (sport !== 'nfl' && sport !== 'nba' && sport !== 'cfb') return NextResponse.json({error:'Invalid sport'}, {status:400,headers:NO_STORE_HEADERS});
  try {
    const data = await snapshot('markets:'+sport);
    if (!data) return NextResponse.json({error:'No market observations have been published yet.'}, {status:503,headers:NO_STORE_HEADERS});
    return NextResponse.json(publicMarkets(data,sport), {headers:PUBLIC_CACHE_HEADERS.live});
  } catch {
    return NextResponse.json({error:'Market observations are temporarily unavailable.'}, {status:503,headers:NO_STORE_HEADERS});
  }
}
