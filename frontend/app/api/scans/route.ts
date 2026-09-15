import { NextResponse } from 'next/server';
import { snapshots } from '@/lib/database';
import { scanStatus } from '@/lib/scanStatus';
export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const data=await snapshots(['scan:nfl','scan:nba']);
    return NextResponse.json({nfl:scanStatus(data['scan:nfl']),nba:scanStatus(data['scan:nba'])}, {headers:{'Cache-Control':'no-store'}});
  } catch {
    return NextResponse.json({error:'Daily scan status is temporarily unavailable.'},{status:503});
  }
}
