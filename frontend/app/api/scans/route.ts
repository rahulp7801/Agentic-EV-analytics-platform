import { NextResponse } from 'next/server';
import { snapshot } from '@/lib/database';
import { scanStatus } from '@/lib/scanStatus';
export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const [nfl,nba]=await Promise.all([snapshot('scan:nfl'),snapshot('scan:nba')]);
    return NextResponse.json({nfl:scanStatus(nfl),nba:scanStatus(nba)}, {headers:{'Cache-Control':'no-store'}});
  } catch {
    return NextResponse.json({error:'Daily scan status is temporarily unavailable.'},{status:503});
  }
}
