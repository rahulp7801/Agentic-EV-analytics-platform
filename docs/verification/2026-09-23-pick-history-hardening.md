# Pick-history integrity hardening — 2026-09-23

## Scope

Fortify the consumer-facing pick board and its publisher. The live model,
qualification thresholds, frozen shadow artifact, settlement database writes,
API quotas, schedules, and collection requests are unchanged.

## Reproduced failures

- TypeScript accepted a final result in a snapshot published before kickoff or
  before the result observation, once the viewer's clock had advanced far enough.
- `Number(null)` and other coercions could turn missing/malformed actual values
  into a numeric result. This is particularly misleading for an under pick.
- A malformed retained sample size could crash Python's board sort and prevent
  publication of neighboring valid picks. Invalid IDs and display fields could
  also reach the public boundary and invalidate a whole snapshot there.
- Python replay included a settlement even when its observation was later than
  the requested publication time. Naive publication times used the host timezone.
- The pick-board consumer allowed a quote shortly after capture and stakes above
  the ledger's 5% cap through the generic signal validator.

Before the fixes, the new tests reproduced 11 backend failures and three failing
frontend regression groups. The negative-push case was already rejected by an
existing arithmetic check and is retained as a boundary regression.

## Changes

- Validate final game and settlement timestamps against snapshot publication time.
  The backend publishes pending until the verified result is known at that time.
- Require finite numeric result values without string, boolean, or null coercion.
  An authentic zero is still valid.
- Validate retained selection IDs, sample sizes, trade plans, numeric display
  bounds, quote age, and forecast chronology before grouping or sorting.
- Ignore captures after the requested publication time before identity grouping.
- Require an explicit timezone for publication times.
- Enforce quote-at-or-before-capture and the existing 5% stake cap in the public
  pick-board contract. Existing elapsed-lock/kickoff behavior remains covered.
- Add a shared synthetic JSON fixture: Python reproduces the exact board using
  real quote/stat commitment verifiers; TypeScript consumes that same output,
  including a verified zero result. The fixture is not market evidence.

## Verification

- Initial targeted backend run: 61 passing pick-board, daily-pipeline and scheduled
  scan tests. Additional strict-result and cross-language tests are in full CI.
- All 163 frontend tests pass locally; TypeScript typecheck passes.
- Read-only production comparison: complete generated boards are identical before
  and after hardening for NBA, NFL, and CFB. NFL retains three verified historical
  picks (one win, two losses); NBA/CFB have none. All currently have zero current
  picks. Only aggregate parity results were retained locally.
- Full backend, PostgreSQL, worker-image, frontend build, and security gates run
  on the pull request; production readiness runs on the merged commit.

## Limits

This strengthens the integrity of outputs; it is not new evidence of profitable
picks. The frozen prospective candidate trial still needs future observations.
At the production inspection, no shadow-validation snapshot had been published.
No sports API request, paid refresh, purchase, or wager was made for this phase.
