export function databaseConfig(value: string | undefined, ca?: string, hosted=false) {
  if (!value) throw new Error('Service unavailable');
  const url = new URL(value.replace('postgresql+psycopg://', 'postgresql://'));
  if(hosted && url.searchParams.get('sslmode')!=='verify-full') {
    throw new Error('Hosted database requires certificate and hostname verification');
  }
  if (!ca) return {connectionString: url.toString()};
  if (url.searchParams.get('sslmode') !== 'verify-full') {
    throw new Error('Custom database CA requires sslmode=verify-full');
  }
  // pg reparses URL SSL options after Pool options; avoid replacing the explicit CA.
  for (const key of ['sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'ssl']) url.searchParams.delete(key);
  return {connectionString: url.toString(), ssl: {ca, rejectUnauthorized: true}};
}
