import { NextResponse } from 'next/server';
import { snapshot } from '@/lib/database';
import { publicPropScreen } from '@/lib/propScreens';
import {NO_STORE_HEADERS,PUBLIC_CACHE_HEADERS} from '@/lib/publicCache';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const sport=new URL(request.url).searchParams.get('sport');
  if (sport !== 'nfl' && sport !== 'nba' && sport !== 'cfb') return NextResponse.json({error:'Invalid sport'}, {status:400,headers:NO_STORE_HEADERS});
  try {
    const data=await snapshot('prop-screens:'+sport);
    if (!data) return NextResponse.json({error:'No prop screens have been published yet.'}, {status:503,headers:NO_STORE_HEADERS});
    return NextResponse.json(publicPropScreen(data), {headers:PUBLIC_CACHE_HEADERS.live});
  } catch {
    return NextResponse.json({error:'Prop screens are temporarily unavailable.'}, {status:503,headers:NO_STORE_HEADERS});
  }
}
