import { NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';

// Force dynamic — never cache this route handler.
export const dynamic = 'force-dynamic';

const ROOT = path.join(process.cwd(), '..');
const LOCK_FILE = path.join(ROOT, '.scan_lock');
const LOCK_MAX_AGE_MS = 10 * 60 * 1000; // 10 min stale threshold

function isScanRunning(): boolean {
  if (!fs.existsSync(LOCK_FILE)) return false;
  try {
    const written = new Date(fs.readFileSync(LOCK_FILE, 'utf-8').trim()).getTime();
    if (Date.now() - written > LOCK_MAX_AGE_MS) {
      try { fs.unlinkSync(LOCK_FILE); } catch { /* ignore */ }
      return false;
    }
  } catch {
    try { fs.unlinkSync(LOCK_FILE); } catch { /* ignore */ }
    return false;
  }
  return true;
}

export async function POST(req: Request) {
  if (isScanRunning()) {
    return NextResponse.json({ status: 'already_running', message: 'Scan already in progress.' });
  }

  let teamA = 'NY', teamB = 'HOU', dateStr = '', force = false;
  try {
    const body = await req.json();
    if (body.team_a) teamA = body.team_a;
    if (body.team_b) teamB = body.team_b;
    if (body.date)   dateStr = body.date;
    if (body.force)  force = true;
  } catch { /* use defaults */ }

  fs.writeFileSync(LOCK_FILE, new Date().toISOString());

  // Clear the signals cache immediately so the frontend never reads stale data
  // from a previous scan while the new one is running or if it exits early.
  const CACHE_FILE = path.join(ROOT, 'frontend', 'public', 'signals_cache.json');
  try {
    fs.writeFileSync(
      CACHE_FILE,
      JSON.stringify({
        generated_at: new Date().toISOString(),
        game: { home_team: teamB, away_team: teamA, date: dateStr },
        signals: [],
      }),
    );
  } catch { /* non-fatal — Python will overwrite anyway */ }

  const args = ['scan_game_ev.py', '--team-a', teamA, '--team-b', teamB];
  if (dateStr) args.push('--date', dateStr);
  if (force) args.push('--force');

  // Pipe stdout/stderr to scan_out.txt for debugging. Using 'pipe' + stream.write
  // avoids Windows fd-inheritance issues with direct fd passing to spawn.
  const LOG_FILE = path.join(ROOT, 'scan_out.txt');
  const logStream = fs.createWriteStream(LOG_FILE, { flags: 'w' });
  const proc = spawn('python', args, {
    cwd: ROOT,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
  });
  proc.stdout?.pipe(logStream);
  proc.stderr?.pipe(logStream);

  proc.on('exit', () => {
    try { fs.unlinkSync(LOCK_FILE); } catch { /* already deleted */ }
  });

  proc.on('error', () => {
    try { fs.unlinkSync(LOCK_FILE); } catch { /* already deleted */ }
  });

  return NextResponse.json({
    status: 'started',
    message: `Scan started for ${teamA} vs ${teamB}.`,
    team_a: teamA,
    team_b: teamB,
  });
}

const PROGRESS_FILE = path.join(ROOT, '.scan_progress.json');

function readProgress(): Record<string, unknown> | null {
  try {
    if (!fs.existsSync(PROGRESS_FILE)) return null;
    return JSON.parse(fs.readFileSync(PROGRESS_FILE, 'utf-8'));
  } catch {
    return null;
  }
}

export async function GET() {
  const scanning = isScanRunning();
  const progress = scanning ? readProgress() : null;
  return NextResponse.json({ scanning, progress });
}
