import type { Client, QueryResult, QueryResultRow } from 'pg';
import {databaseFailure,type DatabaseOperation,type DatabasePhase,type FailureObserver} from './databaseFailure.ts';

import {QueryAdmission} from './queryAdmission.ts';

type DatabaseClient = Pick<Client, 'connect' | 'query' | 'end'>;
const admission = new QueryAdmission();

export async function queryWithClient<T extends QueryResultRow>(
  client: DatabaseClient,
  text: string,
  values: unknown[] = [],
  operation:DatabaseOperation='unspecified',
  observer?:FailureObserver,
): Promise<QueryResult<T>> {
  const started=performance.now();
  const report=(error:unknown,phase:DatabasePhase)=>{
    try {observer?.(databaseFailure(error,phase,operation,performance.now()-started,admission.activeCount));}
    catch { /* A failed observer must not mask a database failure or leak a connection. */ }
  };
  // Wait briefly before rejecting a burst, retaining the six-connection cap.
  let release: () => void;
  try {
    release = await admission.acquire();
  } catch (error) {
    report(error,'backpressure');
    await client.end().catch(error=>report(error,'close'));
    throw error;
  }
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
    finally {release();}
  }
}
