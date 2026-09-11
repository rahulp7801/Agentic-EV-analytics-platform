import { Pool } from 'pg';
import { databaseConfig } from './databaseConfig';
let pool: Pool | undefined;
export const hosted = process.env.VERCEL === '1';
export function database() {
  pool ??= new Pool({...databaseConfig(process.env.DATABASE_URL, process.env.DATABASE_SSL_CA), max: 2, connectionTimeoutMillis: 5000,
    idleTimeoutMillis: 10000, statement_timeout: 5000});
  return pool;
}
export async function snapshot(key: string) {
  const result = await database().query('SELECT payload FROM dashboard_snapshots WHERE snapshot_key = $1', [key]);
  return result.rows[0]?.payload ?? null;
}
