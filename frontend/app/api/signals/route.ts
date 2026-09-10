import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { database, hosted } from '@/lib/database';
import { signalMetrics } from '@/lib/signalMetrics';

// Force dynamic — never cache this route handler (cache file changes after each scan).
export const dynamic = 'force-dynamic';

const CACHE_PATH = path.join(process.cwd(), '..', 'frontend', 'public', 'signals_cache.json');
// Also try the public dir directly (for production build)
const PUBLIC_PATH = path.join(process.cwd(), 'public', 'signals_cache.json');

export async function GET() {
  if (hosted) {
    try {
      const {rows} = await database().query("SELECT payload FROM dashboard_snapshots WHERE snapshot_key LIKE 'signals:%' ORDER BY updated_at DESC LIMIT 100");
      const data = rows.map(r => r.payload);
      return NextResponse.json({generated_at: data[0]?.generated_at ?? null,
        games: data.flatMap(d => d.games ?? []), signals: data.flatMap(d => d.signals ?? []).map(s => signalMetrics(s))},
        {headers: {'Cache-Control':'no-store'}});
    } catch {
      return NextResponse.json({error:'Results are temporarily unavailable.',signals:[]}, {status:503});
    }
  }

  const filePath = fs.existsSync(PUBLIC_PATH) ? PUBLIC_PATH : CACHE_PATH;

  if (!fs.existsSync(filePath)) {
    return NextResponse.json(
      { error: 'No signal cache found. Run scan_game_ev.py first.', signals: [], generated_at: null },
      { status: 404 }
    );
  }

  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const data = JSON.parse(raw);
    data.signals = (data.signals ?? []).map((s: Record<string, unknown>) => signalMetrics(s));
    return NextResponse.json(data, {
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch {
    return NextResponse.json({ error: 'Failed to parse signal cache.', signals: [] }, { status: 500 });
  }
}
