import { hosted } from '@/lib/database';
import { NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';

// Force dynamic — never cache this route handler.
export const dynamic = 'force-dynamic';

import { ROOT, PYTHON } from '@/lib/python';
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
  // Hosted scans run in the authenticated GitHub workflow, never a public subprocess.
  if (hosted) return NextResponse.json({error:'Scans are managed by the scheduled service.'}, {status:403});
  const origin = req.headers.get('origin');
  const host = new URL(req.url).hostname;
  if (!['localhost','127.0.0.1','[::1]'].includes(host) || (origin && new URL(origin).host !== new URL(req.url).host))
    return NextResponse.json({error:'Not authorized'}, {status:403});
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

  if (typeof teamA !== 'string' || typeof teamB !== 'string' || !/^[A-Z]{2,3}$/.test(teamA) || !/^[A-Z]{2,3}$/.test(teamB) || typeof dateStr !== 'string' || (dateStr && !/^\d{4}-?\d{2}-?\d{2}$/.test(dateStr))) {
    return NextResponse.json({error: 'Invalid teams or date'}, {status: 400});
  }
  try {
    fs.writeFileSync(LOCK_FILE, new Date().toISOString(), {flag: 'wx'});
  } catch {
    return NextResponse.json({status: 'already_running'});
  }

  const args = ['scan_game_ev.py', '--team-a', teamA, '--team-b', teamB];
  if (dateStr) args.push('--date', dateStr.replaceAll('-', '')); 
  if (force) args.push('--force');

  // Pipe stdout/stderr to scan_out.txt for debugging. Using 'pipe' + stream.write
  // avoids Windows fd-inheritance issues with direct fd passing to spawn.
  const LOG_FILE = path.join(ROOT, 'scan_out.txt');
  const logStream = fs.createWriteStream(LOG_FILE, { flags: 'w' });
  const proc = spawn(PYTHON, args, {
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
  if (hosted) return NextResponse.json({scanning:false,managed:true,progress:null});
  const scanning = isScanRunning();
  const progress = scanning ? readProgress() : null;
  return NextResponse.json({ scanning, progress });
}
