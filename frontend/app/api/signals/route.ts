import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

// Force dynamic — never cache this route handler (cache file changes after each scan).
export const dynamic = 'force-dynamic';

const CACHE_PATH = path.join(process.cwd(), '..', 'frontend', 'public', 'signals_cache.json');
// Also try the public dir directly (for production build)
const PUBLIC_PATH = path.join(process.cwd(), 'public', 'signals_cache.json');

export async function GET() {
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
    return NextResponse.json(data, {
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch {
    return NextResponse.json({ error: 'Failed to parse signal cache.', signals: [] }, { status: 500 });
  }
}
