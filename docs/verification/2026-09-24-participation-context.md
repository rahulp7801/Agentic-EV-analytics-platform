# Recorded participation context correction

## Read-only production evidence

At 2026-09-24 15:26 UTC, replayed scan `87af054136f74059b72a0fe4d205585e` from one repeatable-read, read-only database transaction. The scan retained 19 NFL selections across seven players blocked by `teammate_availability_unmodeled`.

For 19 retained descriptive comparisons whose participants resolve uniquely through the frozen public nflverse identity archive, the old SQL labeled 37 comparison memberships as absent: 36 missing participant rows and one stored zero snap count. The new SQL reports all 37 as unknown. These counts are overlapping comparison memberships, not distinct games, accepted picks, or outcomes. One additional comparison for A.J. Terrell Jr. was not replayed because the display name did not uniquely resolve through the archived identity source; no identity was guessed. Per-comparison inputs and results are in `2026-09-24-participation-context-audit.json`.

## Correction

- Team-level coverage no longer turns a missing participant into an absent player. Exact participant identity, team, source fields, and a single matching participation row are required.
- NFL source ingestion historically used `fillna(0)`. Existing zero counts cannot distinguish source zeros from missing values, so they remain unknown. Positive unit snap counts remain descriptive participation evidence. No original-source zero reconstruction is attempted in this release.
- NBA zero-minute comparisons require an explicit, valid participant row. Missing, null, invalid, wrong-team, and ambiguous evidence is unknown. Zero minutes do not prove injury absence.
- New evidence uses `recorded-participation-v2` and includes `unknown_games`. Unknown games are excluded from cohort hit rates. All-unknown samples remain visible as coverage gaps.
- The public projection withholds unversioned legacy comparisons without discarding their independently valid current injury/roster reports. Frozen prediction payloads remain untouched. Unsupported new versions or malformed cohorts are rejected.
- The evidence panel uses participation labels and unknown counts; it no longer says “When absent.” A cohort with games must have both a finite mean and hit rate.

## Invariants and checkpoint

Model probabilities, qualification thresholds, injury gates, frozen shadow code/versions, source ingestion, settlements, API limits, and collection scheduling are unchanged. This does not qualify the 19 blocked selections or demonstrate an edge. No quote collection, purchases, or production data writes are part of the audit or fix.

Regression coverage executes the real PostgreSQL SQL for NFL/NBA and teammate/opponent contexts, including cutoff exclusion, missing rows despite team coverage, null/zero counts, invalid source records, wrong-team records, duplicates, and all-unknown samples. Frontend regressions cover legacy suppression, retained injury evidence, finite cohort statistics, bounded unknown counts, and NBA zero-minute separation.

Next evidence checkpoint: ordinary reserved pregame stages beginning CFB 2026-09-24 21:30 UTC and NFL 22:15 UTC. Verify newly captured context version and unknown counts, and the PR217 timestamp adapter on fresh shadow attempts. Do not request extra quotes to exercise either fix. ATL/GB starts 2026-09-25 00:15 UTC; authenticate final results before scoring the ten pending distinct role-shadow thresholds. Fifty distinct paired games are required before that protocol can support predictive evidence.


## Explanation-copy follow-up

PR221 merged as `8db8e95` after CI36020473631 passed (1,116 backend, 174 frontend, 36 PostgreSQL integration, 9 migration tests; CodeQL36020467965). Local 1440px/390px browser checks covered NFL, NBA zero minutes, and legacy context without page errors, horizontal overflow, or targeted WCAG A/AA violations. The mobile participation card was visually inspected.

The scanner also had an availability explanation bullet claiming an exact on/off comparison. Future captures now describe participation summaries. The public projection withholds that obsolete generated bullet on retained forecasts; other explanation bullets and independently verified current injury evidence remain visible. The immutable payload itself is not rewritten. A regression verifies source-array immutability and unchanged probability.


## Production verification and release retry

PR221 release `36021021459` passed hosted schema, deployment, and public access/readiness checks. A direct production API check at 2026-09-24 15:42:32 UTC returned 100 NFL library forecasts, zero invalid signals, 100 retained observed availability reports, and zero exposed legacy comparison objects. All 19 replayed positive-participation cohorts in the archived audit equal their original values; all original absent counts were reproduced before correction.

PR222 merged as `313491aa7ce35f0785a952f53a468c1946af3055` after CI `36021314405` (1,116 backend, 175 frontend, 36 PostgreSQL integration, 9 migration tests) and CodeQL `36021311032` passed. Its merge did not start a master workflow within repeated checks over six minutes, despite the workflow remaining active. The live API consequently still returned the old explanation bullet in those 100 records. This verification commit provides a new normal protected-master push through the reviewed PR path to retry release. Do not claim the wording correction is deployed until an exact-head release and public verification pass.

Quota checkpoint at 15:33 UTC remained 12/20 daily and 322/450 rolling credits; all remaining daily credits are reserved. No additional quote collection or data writes were triggered. The next fresh prediction must retain participation evidence version `recorded-participation-v2`, explicit unknown counts, and the corrected participation-summary wording. Existing frozen rows remain immutable.
