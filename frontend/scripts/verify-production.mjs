import { readFile } from 'node:fs/promises';
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

export const requiredCssMarkers = [
  '--accent:#5e5ce6',
  '.terminal-layout{',
  '__hero h1{',
];

export function readinessStatuses(path, { paidEnabled, publicEnabled }) {
  if (paidPipelinePaths.includes(path)) return paidEnabled ? [200] : [200, 503];
  if (publicPipelinePaths.includes(path)) return paidEnabled || publicEnabled ? [200] : [200, 503];
  throw new Error(`Unclassified readiness endpoint: ${path}`);
}

function expectedPublicCapture(path, report) {
  if (!report) return undefined;
  const url = new URL(path, 'https://readiness.invalid');
  const sport = url.searchParams.get('sport');
  if (url.pathname === '/api/markets') return report.markets?.[sport]?.captured_at;
  if (url.pathname === '/api/games') return report.schedules?.[sport]?.captured_at;
  return undefined;
}

export async function verifyProduction({
  base = process.env.PRODUCTION_BASE_URL || 'https://agentic-ev-analytics-platform.vercel.app',
  fetchImpl = fetch,
  paidEnabled = process.env.DATA_PIPELINE_ENABLED === 'true',
  publicEnabled = process.env.PUBLIC_DATA_PIPELINE_ENABLED === 'true',
  expectedPublicReport,
} = {}) {
  base = base.replace(/\/$/, '');
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

  const cacheKey = encodeURIComponent(process.env.GITHUB_SHA || Date.now().toString());
  const home = await check(`/?readiness=${cacheKey}`, [200], {
    cache: 'no-store',
    headers: { 'cache-control': 'no-cache' },
  });
  if (home.headers.get('x-content-type-options') !== 'nosniff' || !home.headers.get('content-security-policy')) {
    throw new Error('Production security headers are missing');
  }
  const html = await home.text();
  const stylesheetUrls = [...html.matchAll(/href=["']([^"']+\.css(?:\?[^"']*)?)["']/gi)]
    .map(match => new URL(match[1], base).toString());
  if (!stylesheetUrls.length) throw new Error('Production stylesheets are missing');
  const css = (await Promise.all(stylesheetUrls.map(async url => {
    const response = await fetchImpl(url, { signal: AbortSignal.timeout(20000), redirect: 'manual' });
    if (response.status !== 200) throw new Error(`Production stylesheet returned HTTP ${response.status}`);
    return response.text();
  }))).join('\n');
  for (const marker of requiredCssMarkers) {
    if (!css.includes(marker)) throw new Error(`Production stylesheet is stale or incomplete: ${marker}`);
  }
  await check('/api/scan', [403], { method: 'POST' });
  await check('/.env', [404]);
  await check('/signals_cache.json', [404]);

  for (const path of [...paidPipelinePaths, ...publicPipelinePaths]) {
    const response = await check(path, readinessStatuses(path, { paidEnabled, publicEnabled }));
    if (response.status === 503) {
      console.log(`::warning::${path} unavailable; its data pipeline is disabled`);
    }
    const capturedAt = expectedPublicCapture(path, expectedPublicReport);
    if (capturedAt !== undefined) {
      const body = await response.json();
      if (body?.captured_at !== capturedAt) {
        throw new Error(`${path}: deployed capture does not match this collection run`);
      }
    }
  }
}

export async function verifyProductionWithRetry(
  options = {},
  {
    attempts = 1,
    delayMs = 0,
    wait = delay => new Promise(resolve => setTimeout(resolve, delay)),
    log = message => console.log(message),
  } = {},
) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await verifyProduction(options);
      return;
    } catch (error) {
      lastError = error;
      if (attempt === attempts) break;
      log(`::warning::Production verification attempt ${attempt}/${attempts} failed: ${error.message}`);
      await wait(delayMs);
    }
  }
  throw lastError;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const expectedPublicReport = process.env.PUBLIC_DATA_REPORT_PATH
    ? JSON.parse(await readFile(process.env.PUBLIC_DATA_REPORT_PATH, 'utf8'))
    : undefined;
  const attempts = Number.parseInt(process.env.PRODUCTION_VERIFY_ATTEMPTS || '1', 10);
  const delayMs = Number.parseInt(process.env.PRODUCTION_VERIFY_DELAY_MS || '0', 10);
  await verifyProductionWithRetry(
    { expectedPublicReport },
    { attempts: Number.isInteger(attempts) && attempts > 0 ? attempts : 1,
      delayMs: Number.isInteger(delayMs) && delayMs >= 0 ? delayMs : 0 },
  );
}
