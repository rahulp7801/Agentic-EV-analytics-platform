import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { databaseQuery, hosted } from '@/lib/database';
import { publicSignalSnapshots, publicPlayerProfile } from '@/lib/signalMetrics';
import type { Sport } from '@/lib/types';

// Force dynamic — never cache this route handler (cache file changes after each scan).
export const dynamic = 'force-dynamic';

const CACHE_PATH = path.join(process.cwd(), '..', 'frontend', 'public', 'signals_cache.json');
// Also try the public dir directly (for production build)
const PUBLIC_PATH = path.join(process.cwd(), 'public', 'signals_cache.json');

export async function GET(request: Request) {
  const requestedSport = new URL(request.url).searchParams.get('sport');
  if (requestedSport !== null && requestedSport !== 'nfl' && requestedSport !== 'nba') {
    return NextResponse.json({ error: 'Unsupported sport.' }, { status: 400 });
  }
  const sport = requestedSport as Sport | null;

  if (hosted) {
    try {
      const pattern = sport ? `signals:${sport}:%` : 'signals:%';
      const profileKeys=sport ? ['player-profiles:'+sport] : ['player-profiles:nfl','player-profiles:nba'];
      const {rows} = await databaseQuery<{snapshot_key:string;payload: unknown}>(
        'SELECT snapshot_key,payload FROM dashboard_snapshots WHERE snapshot_key LIKE $1 OR snapshot_key = ANY($2::text[]) ORDER BY updated_at DESC LIMIT 102',
        [pattern,profileKeys],
      );
      const data = rows.filter(row=>row.snapshot_key.startsWith('signals:')).slice(0,100).map(r => r.payload);
      const now=Date.now();
      const result=publicSignalSnapshots(data,now,sport ?? undefined);
      // Profile collection is independent; its failure must not hide real forecasts.
      try {
        const profiles=Object.fromEntries(rows.filter(row=>profileKeys.includes(row.snapshot_key)).map(row=>[row.snapshot_key,row.payload])) as Record<string,{profiles?:unknown[]}>;
        result.signals=result.signals.map(signal=>{
          const values=profiles['player-profiles:'+signal.sport]?.profiles;
          if(!Array.isArray(values) || values.length>500) return signal;
          const matches=values.map(value=>publicPlayerProfile(value,signal.sport,signal.player,now)).filter(Boolean);
          return matches.length===1 ? {...signal,player_profile:matches[0]} : signal;
        });
      } catch { /* Retain the captured forecast's own roster portrait. */ }
      return NextResponse.json(result,
        {headers: {'Cache-Control':'no-store'}});
    } catch {
      return NextResponse.json({error:'Results are temporarily unavailable.',signals:[]}, {status:503});
    }
  }

  const filePath = fs.existsSync(PUBLIC_PATH) ? PUBLIC_PATH : CACHE_PATH;

  if (!fs.existsSync(filePath)) {
    return NextResponse.json(
      { error: 'No signal snapshot has been published yet.', signals: [], generated_at: null },
      { status: 503 }
    );
  }

  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const data = JSON.parse(raw);
    return NextResponse.json(publicSignalSnapshots([data], Date.now(), sport ?? undefined), {
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch {
    return NextResponse.json({ error: 'Results are temporarily unavailable.', signals: [] }, { status: 503 });
  }
}
