import { hosted, snapshot } from '@/lib/database';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { NextResponse } from 'next/server';
import { ROOT, PYTHON } from '@/lib/python';
import { metricCohort, metricLedgerArgs, metricSnapshotKey } from '@/lib/metricCohort';
export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  const cohort = metricCohort(request.url);
  if (!cohort) return NextResponse.json({error: 'Invalid metric cohort.'}, {status: 400});
  try {
    if (hosted) {
      const data = await snapshot(metricSnapshotKey(cohort));
      if (!data) return NextResponse.json({error:'No evaluation metrics have been published yet.'}, {status:503});
      return NextResponse.json(data, {headers:{'Cache-Control':'no-store'}});
    }
    const { stdout } = await promisify(execFile)(PYTHON, metricLedgerArgs(cohort), {
      cwd: ROOT, timeout: 20000, env: {...process.env, PYTHONIOENCODING: 'utf-8'},
    });
    return NextResponse.json(JSON.parse(stdout), {headers: {'Cache-Control': 'no-store'}});
  } catch {
    return NextResponse.json({error: 'Evaluation metrics are temporarily unavailable.'}, {status: 503});
  }
}
