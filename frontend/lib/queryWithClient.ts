import type { Client, QueryResult, QueryResultRow } from 'pg';

type DatabaseClient = Pick<Client, 'connect' | 'query' | 'end'>;
let activeQueries=0;

export async function queryWithClient<T extends QueryResultRow>(
  client: DatabaseClient,
  text: string,
  values: unknown[] = [],
): Promise<QueryResult<T>> {
  // Per-isolate backpressure; the edge firewall and reader role bound global abuse.
  if(activeQueries>=4) {
    await client.end().catch(()=>undefined);
    throw new Error('Service busy');
  }
  activeQueries++;
  try {
    await client.connect();
    return await client.query<T>(text, values);
  } finally {
    try {await client.end().catch(() => undefined);}
    finally {activeQueries--;}
  }
}
