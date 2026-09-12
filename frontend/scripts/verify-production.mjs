import { pathToFileURL } from 'node:url';

export const paidPipelinePaths = [
  '/api/signals',
  '/api/metrics',
  '/api/metrics?cohort=recommendations',
  '/api/scans',
  '/api/prop-screens?sport=nfl',
  '/api/prop-screens?sport=nba',
];

export const publicPipelinePaths = [
  '/api/markets?sport=nfl',
  '/api/markets?sport=nba',
  '/api/games?sport=nfl',
  '/api/games?sport=nba',
  '/api/gamelogs?sport=nfl',
  '/api/gamelogs?sport=nba',
];

export function readinessStatuses(path, { paidEnabled, publicEnabled }) {
  if (paidPipelinePaths.includes(path)) return paidEnabled ? [200] : [200, 503];
  if (publicPipelinePaths.includes(path)) return paidEnabled || publicEnabled ? [200] : [200, 503];
  throw new Error(`Unclassified readiness endpoint: ${path}`);
}

export async function verifyProduction({
  base = 'https://agentic-ev-analytics-platform.vercel.app',
  fetchImpl = fetch,
  paidEnabled = process.env.DATA_PIPELINE_ENABLED === 'true',
  publicEnabled = process.env.PUBLIC_DATA_PIPELINE_ENABLED === 'true',
} = {}) {
  async function check(path, expected, options = {}) {
    const response = await fetchImpl(base + path, {
      ...options,
      signal: AbortSignal.timeout(20000),
      redirect: 'manual',
    });
    if (!expected.includes(response.status)) {
      throw new Error(`${path}: unexpected HTTP ${response.status}`);
    }
    return response;
  }

  const home = await check('/', [200]);
  if (home.headers.get('x-content-type-options') !== 'nosniff' || !home.headers.get('content-security-policy')) {
    throw new Error('Production security headers are missing');
  }
  await check('/api/scan', [403], { method: 'POST' });
  await check('/.env', [404]);
  await check('/signals_cache.json', [404]);

  for (const path of [...paidPipelinePaths, ...publicPipelinePaths]) {
    const response = await check(path, readinessStatuses(path, { paidEnabled, publicEnabled }));
    if (response.status === 503) {
      console.log(`::warning::${path} unavailable; its data pipeline is disabled`);
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await verifyProduction();
}
