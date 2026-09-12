import { NextResponse } from 'next/server';
import { snapshot } from '@/lib/database';
import { publicPropScreen } from '@/lib/propScreens';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const sport=new URL(request.url).searchParams.get('sport');
  if (sport !== 'nfl' && sport !== 'nba') return NextResponse.json({error:'Invalid sport'}, {status:400});
  try {
    const data=await snapshot('prop-screens:'+sport);
    if (!data) return NextResponse.json({error:'No prop screens have been published yet.'}, {status:503});
    return NextResponse.json(publicPropScreen(data), {headers:{'Cache-Control':'no-store'}});
  } catch {
    return NextResponse.json({error:'Prop screens are temporarily unavailable.'}, {status:503});
  }
}
