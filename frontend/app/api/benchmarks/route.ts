import {NextResponse} from 'next/server';
import weekOne from '@/data/nfl-week1-2026.json';
import {publicForecastBenchmark} from '@/lib/publicBenchmarks';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const sport = new URL(request.url).searchParams.get('sport') ?? 'nfl';
  if (sport !== 'nfl' && sport !== 'nba') {
    return NextResponse.json({error:'Invalid benchmark request.'}, {status:400});
  }
  return NextResponse.json({benchmarks:sport === 'nfl' ? [publicForecastBenchmark(weekOne)] : []},
    {headers:{'Cache-Control':'public, max-age=3600, stale-while-revalidate=86400'}});
}
