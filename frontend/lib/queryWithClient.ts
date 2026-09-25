import type { Client, QueryResult, QueryResultRow } from 'pg';
import {databaseFailure,type DatabaseOperation,type DatabasePhase,type FailureObserver} from './databaseFailure.ts';

type DatabaseClient = Pick<Client, 'connect' | 'query' | 'end'>;
let activeQueries=0;

export async function queryWithClient<T extends QueryResultRow>(
  client: DatabaseClient,
  text: string,
  values: unknown[] = [],
  operation:DatabaseOperation='unspecified',
  observer?:FailureObserver,
): Promise<QueryResult<T>> {
  const started=performance.now();
  const report=(error:unknown,phase:DatabasePhase)=>{
    try {observer?.(databaseFailure(error,phase,operation,performance.now()-started,activeQueries));}
    catch { /* A failed observer must not mask a database failure or leak a connection. */ }
  };
  // Per-isolate backpressure; the reader role also caps global database connections.
  if(activeQueries>=6) {
    const error=new Error('Service busy');
    report(error,'backpressure');
    await client.end().catch(error=>report(error,'close'));
    throw error;
  }
  activeQueries++;
  let phase:DatabasePhase='connect';
  try {
    await client.connect();
    phase='query';
    return await client.query<T>(text, values);
  } catch(error) {
    report(error,phase);
    throw error;
  } finally {
    try {await client.end().catch(error=>report(error,'close'));}
    finally {activeQueries--;}
  }
}
