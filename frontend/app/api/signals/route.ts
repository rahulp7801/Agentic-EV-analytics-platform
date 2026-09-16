import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { databaseQuery, hosted } from '@/lib/database';
import { publicSignalSnapshots } from '@/lib/signalMetrics';
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
      const {rows} = await databaseQuery<{payload: unknown}>(
        'SELECT payload FROM dashboard_snapshots WHERE snapshot_key LIKE $1 ORDER BY updated_at DESC LIMIT 100',
        [pattern],
      );
      const data = rows.map(r => r.payload);
      return NextResponse.json(publicSignalSnapshots(data, Date.now(), sport ?? undefined),
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
