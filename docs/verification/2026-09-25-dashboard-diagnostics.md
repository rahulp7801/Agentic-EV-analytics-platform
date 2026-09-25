# Sanitized dashboard failure diagnostics

## Observed problem

Public-data verification runs 36048644110 and 36072577069 encountered `/api/gamelogs?sport=nfl` HTTP 503 responses, followed by successful requests. The route swallowed every exception, so available evidence could not distinguish database connection limits, timeouts, local concurrency rejection, or invalid public row data. No specific root cause is established yet.

A proposed materialized page-date bound returned identical results in five read-only checks (NFL default, exact player, date pagination, NBA default and CFB default). Its apparent initial speedup did not survive reversed-order repeat testing: original NFL query 0.469/0.468/0.468 seconds, alternative 1.062/0.485/0.485 seconds. The query is unchanged; this is not a proven performance fix.

## Change

Database failures emit a structured server-log record with exactly: fixed event name, allowlisted operation, allowlisted phase, allowlisted category, elapsed milliseconds and per-isolate active-query count. No raw errors, messages, stack traces, SQL, request parameters, names, tokens, hostnames, database URLs, or returned rows are logged.

Operations identify game logs, paged forecasts, and single/batched snapshots. Phases distinguish configuration, connection, query, local backpressure and cleanup. Known PostgreSQL/Node codes and exact messages from the installed pg client map to fixed categories. SQLSTATE 57014 is reported as `query_cancelled`, because that code alone does not prove a statement timeout. Unknown values stay `unknown`; they are not printed. Returned-row validation has a separate fixed `dashboard_data_failure` event.

Original errors, generic API errors, HTTP statuses and cache headers are preserved. Queries, TLS requirements, five-second connection/statement limits, six-second client query timeout, six-query per-isolate cap, reader grants and global connection caps are unchanged. Diagnostics cannot replace a query result/error if the log sink itself fails. No retries or collection requests were added.

## Verification

Twelve targeted tests pass, including original connection cleanup and public projection tests plus classification/redaction, malicious error properties, phase attribution, original-error identity, observer failure, local capacity recovery and cleanup-only failure. TypeScript type checking passes. Targeted lint and the production build pass. A built local endpoint, pointed only at an unavailable loopback database port, returned the exact generic HTTP 503 body with `no-store`; its server log contained only `gamelogs / connect / connection_refused`, elapsed time and one active query. Invalid sport returned HTTP 400 with `no-store` and no database event. The owned local server was stopped. CI/deployment results are recorded on the pull request.

## Next evidence checkpoint

For the next naturally occurring 503, inspect the same deployment/request's existing runtime log. A `dashboard_database_failure` record identifies the operation, phase and bounded category. A `dashboard_data_failure` record means returned data failed public validation. A `query_cancelled` event requires further evidence to distinguish timeout from another cancellation. Global connection-limit events cannot be inferred solely from the per-isolate count. If a response has neither record, inspect platform/runtime termination and deployment boundaries; do not attribute it to SQL without evidence.

Do not intentionally induce failures or load-test production. No paid logging service, additional retention, database migration, data collection, or spending is enabled. The existing production smoke check verifies normal readiness; it does not prove the intermittent fault is fixed.

Existing model/prospective checks, qualifications, quota caps and staged reserve remain unchanged; PR #194 remains excluded. The next authenticated NFL/CFB result checkpoint remains September 25 at 04:30 UTC or the first follow-up after final source data becomes available. No demonstrated edge is claimed by this operational change.
