# Immutable prediction retry hardening — 2026-09-23

## Why this phase

A read-only production count found no prospective shadow records yet. The latest
scheduled data run still predates deployment of the collector. No paid refresh
was triggered to manufacture a sample.

While checking persistence, five regression cases reproduced real defects:

1. A valid shadow inference recorded after the five-minute quote window could be
   safely marked unavailable on the first write, but its identical retry failed.
2. The same failure occurred after kickoff.
3. An invalid inference also failed on an identical retry. A transient connection
   error after a successful commit could therefore leave a caller unable to
   confirm completion.
4. Python dictionary equality treated a nested boolean and numeric one as the
   same immutable evidence.
5. An embedded payload `prediction_id` could override the authoritative database
   primary key when predictions were read back.

## Changes

- When excluding a predicted shadow at insertion, retain a server-owned SHA-256
  commitment to its original input. Keep the unavailable status and original
  receipt. An identical retry can match that input without refreshing timestamps
  or making the candidate eligible for evaluation.
- Compare the complete retained record against the expected exclusion projection;
  a matching shadow commitment alone cannot authorize changes to the primary
  forecast, prices, or other evidence.
- Ignore caller-supplied receipt/commitment fields. Keep JSON type distinctions
  during immutable comparison and ignore object key order.
- Return the database primary key as the prediction ID.
- Preserve atomic event-batch writes: a conflicting retry rolls back neighboring
  new predictions and quote inserts.

No migration, data rewrite, model change, threshold change, new provider request,
quota increase, or schedule change is included. The frozen candidate code,
parameters, feature formula, and implementation hash remain untouched.

## Verification

- Five failing regression cases reproduced before the implementation change.
- Initial relevant suite: 81 tests passed after the fix.
- Extended coverage includes simultaneous identical retries, original receipt
  preservation, rejection of altered primary/shadow evidence and forged metadata,
  nonfinite/unsupported rejected inputs, legacy compatibility, and batch rollback.
- A disposable PostgreSQL integration test exercises the same retry and rollback
  contract against the real database implementation. Full regression, worker
  image, frontend, security, and PostgreSQL checks gate the pull request.

## Limits

Original inputs for older unavailable records without a commitment cannot be
reconstructed safely; those records are not rewritten. Exact retries of their
retained representation still work. Unsupported non-JSON objects cannot receive
an input commitment, but an invalid shadow still does not discard its valid
primary forecast. Nonfinite rejected values are only hashed for retry matching;
they are not stored as model output.

These changes improve collection reliability and audit integrity. They provide
no additional predictive or profit evidence. No money was spent or bets placed.
