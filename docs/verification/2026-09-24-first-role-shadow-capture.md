# First prospective role-shadow capture and workload input repair

## Recovery and actual coverage

At 02:06 UTC on September 24, the configured half-hour scanner had not run since September 23 23:54 UTC. The workflow remained enabled and no data workflow was queued or running. The 00:44 UTC scheduled run was a free history refresh, not a quote scan. One ordinary all-sport scan was dispatched through the existing serialized workflow with its normal cache, cadence, credit reservations and staged pregame reserve; no event targeting or reserve bypass was used.

Workflow **35945889336** completed successfully using deployed commit `639f8b0b96dca32cec7ef0f58b023649940204cd`. Scan `87af054136f74059b72a0fe4d205585e` ran from 02:07:38 to 02:08:59 UTC; evaluation snapshots were subsequently published. A successful workflow does not imply complete league coverage:

- NFL: one eligible game, one evaluated, **371 source-committed quotes**, **134 modeled side/line selections across 16 players**.
- CFB: five eligible games, two checked with **zero usable player-prop quotes**, three deferred under the pregame reserve. There are no new CFB forecasts to score.
- NBA: no eligible games in the 48-hour window.
- Quota: **12/20 daily, 322/450 rolling**; the remaining eight daily credits remain protected for staged pregame checks. No purchases, money or bets.

No NFL selections qualified: 56 no-positive-edge, 34 insufficient-sample, 25 uncertainty/edge failures, and 19 blocked by unmodeled teammate availability. These are raw side/line counts, not independent games. Those gates remain unchanged.

## New candidate is collecting prospectively

Independent read-only replay of the hosted ledger validates **10 distinct role-shadow selections with matching two-sided market prices**: seven receiving-yard thresholds and three reception thresholds. All are pending, for the same Atlanta/Green Bay game. They are correlated selections, not ten independent games or evidence of an edge. Twenty raw side records reduce to those ten after deduplication. The broader denominator retains all 134 attempts / 67 earliest selections, including unsupported markets and players outside the four-player source scope.

The frozen candidate's source/implementation commitments, source chronology, exact offer, current roster and server-owned pregame receipt all passed validation. No old forecasts were rewritten. The audit remains `promote=false`; the minimum 50 distinct paired decided games has not been met.

## Concrete remaining failure and repair

The older `history-workload-shadow-v1` recorded 72 `invalid_shadow_input` attempts. A read-only diagnostic reproduced all 72 failures with current, source-validated database histories: asyncpg returned `source_observed_at` as a timezone-aware Python datetime, while the frozen validator passes that value to `datetime.fromisoformat`, which requires a string. The test fixtures had used strings, so the production driver type was previously missed.

A transport adapter now copies rows and converts only aware `source_observed_at` datetimes to UTC ISO strings at the scanner boundary. It rejects naive datetimes rather than inventing a timezone. Game dates remain date objects; stat values, source hashes, ordering and source observation instants remain unchanged. Existing string and missing values continue through the same frozen validator.

The frozen model files, coefficients, feature formula, model/evaluation versions and all retained forecasts are unchanged. This is input serialization, not a model adjustment. Diagnostic replay with the adapter resolves the type error for all 72 rows: 60 reach a valid diagnostic prediction and 12 retain the low-workload exclusion. **Those 60 are retrospective diagnostic results, not new prospective forecasts, and are never written back.** Original unavailable attempts stay in the evaluation denominator.

Regression checks cover all supported NFL/NBA markets, non-UTC aware timestamps, identical frozen output for the original string contract, unchanged input rows/date types, future-observation rejection, naive-time rejection, scanner public-output/exposure equivalence, and the actual asyncpg timestamptz type in disposable PostgreSQL CI.

## Next exact checkpoints

1. The next normally due NFL scan must use the adapter and record workload-shadow attempts without the driver-type error. No repeat quote collection is needed solely to test this repair; successful read-only replay and CI verify the conversion, and the next scan provides prospective evidence.
2. Retain the two-hour pregame reserve stages: CFB September 24 21:30 UTC and NFL September 24 22:15 UTC, followed by the existing one-hour board locks. Scheduler execution timing is not guaranteed.
3. After Atlanta/Green Bay finishes (kickoff September 25 00:15 UTC), authenticate final player statistics and score the ten retained role-shadow thresholds against their captured matching prices. Report pending outcomes honestly and count distinct games separately.
4. For CFB, distinguish missing provider player-prop quotes from model/history failures. Do not publish synthetic odds or invent picks to fill the empty slate.

PR #194 remains unmerged. No credit limit, reserve, qualification threshold, exposure rule or source/chronology requirement was loosened.
