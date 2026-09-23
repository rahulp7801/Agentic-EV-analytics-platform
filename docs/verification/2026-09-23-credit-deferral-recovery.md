# Collection recovery and precise credit deferrals — 2026-09-23

## Recovery performed

Dispatched the existing all-sport scan on master with the existing API key,
20-credit daily allowance, rolling allowance, and pregame reserve intact:
https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/35897017923

The run completed successfully and published fresh scan and shadow-validation
snapshots. Read-only verification found:

- Daily reserved credits stayed at 11 before and after the run.
- NBA: zero eligible games.
- NFL and CFB: one eligible event each, zero paid event-quote attempts, one budget
  deferral each.
- NBA/NFL shadow reports now exist with zero attempts; CFB correctly reports no
  frozen candidate. There are still no new prospective results.

This restores current operational evidence and confirms the immediate blocker.
It does not establish why the external scheduler omitted earlier scanner runs.

## Exact constraint

At usage 11, a four-market request plus the existing 8-credit reserve totals 23,
which exceeds the 20-credit allowance. The ordinary request itself fits, but the
reserve protects the remaining pregame checks. The targeted reserve bypass in
PR #194 remains separate and unmerged.

## Implementation

Add an atomic reservation method returning a fixed reason code alongside the
existing success flag. The existing boolean interface remains available.
Decisions still require both original inequalities:

- daily usage + requested cost + holdback <= daily limit;
- rolling usage + requested cost + holdback <= rolling limit.

Under the same transaction lock, distinguish a hard daily constraint, a hard
rolling constraint, and the pregame holdback. Failed reservations write nothing.
The scanner retains these reasons per event and in aggregate. The public status
projection uses a descriptive label only when an allowlisted reason count exactly
matches the number of deferred events; malformed or mixed data uses the generic
budget label.

## Verification

- 63 targeted quota, cadence, scheduled-scan and reliability tests passed locally.
- Allowance parity covers the observed 11/20 case, hard daily and rolling bounds,
  rolling holdback, exact allowance boundaries, and invalid requests.
- Concurrent reservation tests retain the 8-credit reserve and enforce the hard
  cap when it is released through the existing interface.
- All 169 frontend tests pass; typecheck passes. CI checks the complete backend,
  database, worker image, frontend build, lint, and security before release.

## Next timing question

The reserve is currently released only inside the last hour before kickoff. That
is also the pick board's T-60 capture cutoff. A delayed reserved check may update
research or live forecasts after the frozen board has stopped accepting entries.
The interaction between reserve timing and the prospective pick policy needs a
separate evaluation; neither timing policy is changed by these diagnostics.

No purchase, card use, allowance increase, wager, model change, or qualification
relaxation was introduced. The recovery run used zero additional credits.
