import { hosted, snapshot } from '@/lib/database';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { NextResponse } from 'next/server';
import { ROOT, PYTHON } from '@/lib/python';
import { metricCohort, metricLedgerArgs, metricSnapshotKey, metricSport } from '@/lib/metricCohort';
import { publicMetrics } from '@/lib/publicMetrics';
import {NO_STORE_HEADERS,PUBLIC_CACHE_HEADERS} from '@/lib/publicCache';
export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  const cohort = metricCohort(request.url);
  const sport = metricSport(request.url);
  if (!cohort || !sport) return NextResponse.json({error: 'Invalid metric request.'}, {status:400,headers:NO_STORE_HEADERS});
  try {
    if (hosted) {
      const data = await snapshot(metricSnapshotKey(cohort, sport));
      if (!data) return NextResponse.json({error:'No evaluation metrics have been published yet.'}, {status:503,headers:NO_STORE_HEADERS});
      return NextResponse.json(publicMetrics(data, cohort, sport), {headers:PUBLIC_CACHE_HEADERS.archive});
    }
    const { stdout } = await promisify(execFile)(PYTHON, metricLedgerArgs(cohort, sport), {
      cwd: ROOT, timeout: 20000, env: {...process.env, PYTHONIOENCODING: 'utf-8'},
    });
    return NextResponse.json(publicMetrics(JSON.parse(stdout), cohort, sport), {headers:PUBLIC_CACHE_HEADERS.archive});
  } catch {
    return NextResponse.json({error: 'Evaluation metrics are temporarily unavailable.'}, {status:503,headers:NO_STORE_HEADERS});
  }
}
