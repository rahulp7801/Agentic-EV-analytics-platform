import { Client, type QueryResultRow } from 'pg';
import { databaseConfig } from './databaseConfig';
import { queryWithClient } from './queryWithClient';

export const hosted = process.env.VERCEL === '1';

export function databaseQuery<T extends QueryResultRow>(text: string, values: unknown[] = []) {
  const client = new Client({...databaseConfig(process.env.DATABASE_URL, process.env.DATABASE_SSL_CA,hosted),
    connectionTimeoutMillis: 5000, statement_timeout: 5000,query_timeout:6000});
  return queryWithClient<T>(client, text, values);
}

export async function snapshot<T = Record<string, unknown>>(key: string): Promise<T | null> {
  const result = await databaseQuery<{payload: unknown}>('SELECT payload FROM dashboard_snapshots WHERE snapshot_key = $1', [key]);
  const payload = result.rows[0]?.payload;
  return payload === undefined ? null : payload as T;
}

export async function snapshots<T = Record<string, unknown>>(keys: string[]): Promise<Record<string, T | null>> {
  const result = await databaseQuery<{snapshot_key: string; payload: unknown}>(
    'SELECT snapshot_key,payload FROM dashboard_snapshots WHERE snapshot_key = ANY($1::text[])', [keys]);
  const found = new Map(result.rows.map(item => [item.snapshot_key, item.payload as T]));
  return Object.fromEntries(keys.map(key => [key, found.get(key) ?? null]));
}
