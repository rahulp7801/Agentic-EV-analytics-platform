import { NextResponse } from 'next/server';
import { snapshots } from '@/lib/database';
import { scanStatus } from '@/lib/scanStatus';
import {NO_STORE_HEADERS,PUBLIC_CACHE_HEADERS} from '@/lib/publicCache';
export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const data=await snapshots(['scan:nfl','scan:nba','scan:cfb']);
    return NextResponse.json({nfl:scanStatus(data['scan:nfl']),nba:scanStatus(data['scan:nba']),
      cfb:scanStatus(data['scan:cfb'])}, {headers:PUBLIC_CACHE_HEADERS.status});
  } catch {
    return NextResponse.json({error:'Daily scan status is temporarily unavailable.'},{status:503,headers:NO_STORE_HEADERS});
  }
}
