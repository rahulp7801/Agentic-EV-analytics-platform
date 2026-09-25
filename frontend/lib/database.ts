import { Client, type QueryResultRow } from 'pg';
import { unstable_cache } from 'next/cache';
import { databaseConfig } from './databaseConfig';
import { queryWithClient } from './queryWithClient';
import {databaseFailure,reportDatabaseFailure,type DatabaseOperation} from './databaseFailure';

export const hosted = process.env.VERCEL === '1';

export async function databaseQuery<T extends QueryResultRow>(text: string, values: unknown[] = [], operation:DatabaseOperation='unspecified') {
  let client:Client;
  try {
    client = new Client({...databaseConfig(process.env.DATABASE_URL, process.env.DATABASE_SSL_CA,hosted),
      connectionTimeoutMillis: 5000, statement_timeout: 5000,query_timeout:6000});
  } catch(error) {
    reportDatabaseFailure(databaseFailure(error,'configure',operation,0,0));
    throw error;
  }
  return queryWithClient<T>(client, text, values,operation,reportDatabaseFailure);
}

async function readSnapshot<T = Record<string, unknown>>(key: string): Promise<T | null> {
  const result = await databaseQuery<{payload: unknown}>('SELECT payload FROM dashboard_snapshots WHERE snapshot_key = $1', [key],'snapshot');
  const payload = result.rows[0]?.payload;
  return payload === undefined ? null : payload as T;
}

async function readSnapshots<T = Record<string, unknown>>(keys: string[]): Promise<Record<string, T | null>> {
  const result = await databaseQuery<{snapshot_key: string; payload: unknown}>(
    'SELECT snapshot_key,payload FROM dashboard_snapshots WHERE snapshot_key = ANY($1::text[])', [keys],'snapshots');
  const found = new Map(result.rows.map(item => [item.snapshot_key, item.payload as T]));
  return Object.fromEntries(keys.map(key => [key, found.get(key) ?? null]));
}

// Next's server data cache is shared across requests. The short lifetime keeps
// state transitions bounded while coalescing cache misses from multiple CDN regions.
const cachedSnapshot = unstable_cache(readSnapshot, ['dashboard-snapshot-v1'], {revalidate: 60});
const cachedSnapshots = unstable_cache(readSnapshots, ['dashboard-snapshots-v1'], {revalidate: 60});

export function snapshot<T = Record<string, unknown>>(key: string): Promise<T | null> {
  return hosted ? cachedSnapshot<T>(key) : readSnapshot<T>(key);
}

export function snapshots<T = Record<string, unknown>>(keys: string[]): Promise<Record<string, T | null>> {
  return hosted ? cachedSnapshots<T>(keys) : readSnapshots<T>(keys);
}
