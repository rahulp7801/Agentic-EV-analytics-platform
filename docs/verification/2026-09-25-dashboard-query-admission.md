# Bounded dashboard database admission

## Confirmed failure

Scheduled public verification run 36079710441 failed on the NFL game-log endpoint at 2026-09-25 00:56 UTC, after the sanitized diagnostics release. The retained runtime record identifies `gamelogs / backpressure / local_capacity`, zero elapsed milliseconds, and six active local queries. This establishes immediate local admission rejection for that request. It does not establish the cause of earlier failures or database-wide saturation.

## Fix

Keep the six active connections per isolate and existing global reader cap. Allow at most twelve additional requests to wait in FIFO order for up to two seconds before connecting. Transfer a released slot directly to the next waiter only after connection cleanup finishes. Expired and overflow requests retain the generic unavailable response and sanitized capacity diagnostic. Expired requests never connect or execute SQL. Release handles are idempotent, and successful admission cancels the waiting deadline.

This adds bounded latency during contention. Sustained overload, slow queries, or platform-wide saturation can still return unavailable responses. No retries, connection-limit increase, SQL changes, cache changes, collection, model changes, or paid services are introduced.

## Verification

All 193 frontend tests pass; TypeScript checking, focused ESLint, and the production build pass. The frontend suite exercises burst admission, FIFO ordering, six-connection and twelve-waiter bounds, timeout removal, no connection after timeout, deadline cancellation, cleanup completion before slot reuse, original error propagation, diagnostics, and recovery after query failure. CI and deployment results are recorded on the pull request.

The recovery host lacks the original D: checkout, so the change was made in a fresh temporary clone of remote master. No credentials or original local evidence were copied. Installed Next documentation was unavailable at the instructed local path; the installed README and official unstable_cache guide were consulted. This change does not alter a Next API or caching behavior.

## Next checkpoints

After deployment, run ordinary read-only production readiness checks without collection or intentional production load. Inspect the next scheduled public-data verification and retained runtime records for recurrence. A passing smoke check confirms current availability, not permanent elimination of intermittent errors.

The next authenticated NFL/CFB outcome checkpoint remains September 25 at 04:30 UTC or the first follow-up after final source data becomes available. The next day's CFB checkpoint is September 26 at 04:30 UTC. Frozen evaluations, qualification requirements, staged reserve, 20 daily / 450 rolling credit limits, and the exclusion of PR #194 remain unchanged. This reliability fix is not evidence of a betting edge.
