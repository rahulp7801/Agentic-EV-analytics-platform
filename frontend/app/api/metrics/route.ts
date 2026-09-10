import { execFile } from 'child_process';
import { promisify } from 'util';
import { NextResponse } from 'next/server';
import { ROOT, PYTHON } from '@/lib/python';
export const dynamic = 'force-dynamic';
export async function GET() {
  try {
    const { stdout } = await promisify(execFile)(PYTHON, ['-m', 'sportsbet.ledger'], {
      cwd: ROOT, timeout: 20000, env: {...process.env, PYTHONIOENCODING: 'utf-8'},
    });
    return NextResponse.json(JSON.parse(stdout), {headers: {'Cache-Control': 'no-store'}});
  } catch {
    return NextResponse.json({error: 'Evaluation metrics unavailable. Check the local Python environment.'}, {status: 503});
  }
}
