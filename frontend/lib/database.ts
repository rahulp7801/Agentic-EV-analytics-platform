import { Pool } from 'pg';
const url = process.env.DATABASE_URL?.replace('postgresql+psycopg://', 'postgresql://');
let pool: Pool | undefined;
export const hosted = process.env.VERCEL === '1';
export function database() {
  if (!url) throw new Error('Service unavailable');
  pool ??= new Pool({connectionString: url, max: 2, connectionTimeoutMillis: 5000,
    idleTimeoutMillis: 10000, statement_timeout: 5000});
  return pool;
}
export async function snapshot(key: string) {
  const result = await database().query('SELECT payload FROM dashboard_snapshots WHERE snapshot_key = $1', [key]);
  return result.rows[0]?.payload ?? null;
}
