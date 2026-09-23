# Reserve timing before the frozen pick-board cutoff — 2026-09-23

## Confirmed conflict

The board policy `pregame-t60-v1` accepts captures only through T-60. The previous
scanner retained two full quote checks until T-60, so any processing delay could
make a reserve-funded capture too late for the board. Earlier ordinary-budget
captures remained eligible; this was a collection opportunity failure, not proof
that the model had or lacked an edge.

## Staged collection policy

For the existing all-sport daily limit of 20 and four-credit widest market set:

| Time before kickoff | Credits still held back | Collection behavior |
| --- | ---: | --- |
| More than 120 minutes | 8 | Preserve both checks |
| More than 60, at most 120 minutes | 4 | Allow one check before the board locks |
| At most 60 minutes | 0 | Allow the remaining final-hour check |

NBA-only scans use the same stages with 6/3/0 credits. Small configured budgets
that previously had no reserve still have none. The reserve is shared across the
scan, not allocated separately to every event or league. It cannot guarantee a
quote or qualified pick for every game.

The new T-120 cadence transition makes the next regular scan eligible even when
an earlier distant quote would otherwise delay it. Within each league, final-hour
events remain first, followed by events in the T-120 window, then more distant
events. Existing quality ranking and rotation apply within those groups.

The T-120 opening leaves one hour before the board locks. Offline checks cover
each minute offset in a 30-minute scheduler cycle and allow a full 20-minute
worker runtime. These checks assume the scheduler runs: GitHub queue delays,
missed schedules, provider failures, and large slates can still miss the cutoff.
The existing dashboard must continue reporting stale or overdue collection.

## Unchanged controls

- Daily cap 20 and rolling cap 450 remain unchanged; every request still passes
  the atomic ledger reservation and applicable holdback.
- At observed usage 11/20, the earlier check can reserve four credits (11+4+4=19),
  leaving five unused. Another such pre-lock check is blocked; one final-hour
  four-credit request can fit (15+4=19).
- No targeted bypass is introduced. An explicit distant-event scan keeps the
  full reserve. PR #194 remains separate and unmerged.
- No changes to the board cutoff, quote freshness, source validation, immutable
  ledger, probabilities, qualification thresholds, stakes, settlement, or frozen
  shadow-model implementation/coefficients.
- No purchase, card charge, subscription, allowance increase, or wager. Production
  scans may consume existing API-key credits earlier within the same limits.

## Verification

151 targeted cadence, scanner, scheduling and board tests passed locally. The
priority regression was additionally strengthened and rerun successfully before
commit. Coverage includes all NBA/NFL/CFB windows and exact boundaries, low-budget
behavior, daily/rolling limits, repeated scans, one retained final-hour check,
pre-lock event priority, and the absence of a distant targeted bypass.

An existing synthetic fixture with real quote commitments passes the actual
pick-board validator after the staged reservation. Its T-120 capture becomes a
locked board entry under the unchanged `pregame-t60-v1` policy. Existing tests
continue rejecting captures after the cutoff. This is offline pipeline proof,
not a new real recommendation or prospective performance result.

No provider API calls were made for these tests. Full backend, PostgreSQL,
frontend, worker-image and security CI must pass before production release.
