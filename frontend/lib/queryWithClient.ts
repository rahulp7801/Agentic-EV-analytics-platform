import type { Client, QueryResult, QueryResultRow } from 'pg';

type DatabaseClient = Pick<Client, 'connect' | 'query' | 'end'>;

export async function queryWithClient<T extends QueryResultRow>(
  client: DatabaseClient,
  text: string,
  values: unknown[] = [],
): Promise<QueryResult<T>> {
  try {
    await client.connect();
    return await client.query<T>(text, values);
  } finally {
    await client.end().catch(() => undefined);
  }
}
