import { hosted, snapshot } from '@/lib/database';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { NextResponse } from 'next/server';
import { ROOT, PYTHON } from '@/lib/python';
export const dynamic = 'force-dynamic';
export async function GET() {
  try {
    if (hosted) return NextResponse.json(await snapshot('metrics:all') ?? {sample_size:0,pending_count:0,settled_count:0}, {headers:{'Cache-Control':'no-store'}});
    const { stdout } = await promisify(execFile)(PYTHON, ['-m', 'sportsbet.ledger'], {
      cwd: ROOT, timeout: 20000, env: {...process.env, PYTHONIOENCODING: 'utf-8'},
    });
    return NextResponse.json(JSON.parse(stdout), {headers: {'Cache-Control': 'no-store'}});
  } catch {
    return NextResponse.json({error: 'Evaluation metrics are temporarily unavailable.'}, {status: 503});
  }
}
