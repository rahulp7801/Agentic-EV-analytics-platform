# Reject invalid snap-count ingestion before writes

## Defect and repair

The prior importer normalized `offense_snaps` and `defense_snaps` with `fillna(0).astype('int64')`. Missing values could become synthetic zeros and fractional values could be silently truncated, then committed as source-backed participation.

`prepare_snap_counts` now requires explicit numeric, finite, nonnegative whole counts within the database SMALLINT range. Null, NaN, infinity, negative, fractional, oversized, boolean, and text counts reject the affected season before its snap-count transaction opens. Duplicate game/player identities are also rejected before upsert. Previously written seasons and other refresh stages are not rolled back; the existing refresh failure contract reports a failed refresh. No invalid rows are silently substituted into the previous snap dataset.

Regular-season scope, unidentified-row filtering, field names/order, explicit source zeros, row hashes, batch hashes, source timestamps, and append/upsert behavior remain unchanged for valid source input. Historical stored zeros remain unknown in descriptive context under the existing policy; this release does not reclassify them or establish injury absence.

## Free-source compatibility audit

At 2026-09-24 17:02 UTC, downloaded the three public nflverse Parquet assets used by the existing loader, retained their bytes alongside this note, and compared old versus new normalized row commitments. No database writes or odds requests were made.

| Season | Regular identified rows | Missing snap counts | Row commitments unchanged |
| --- | ---: | ---: | --- |
| 2024 | 25,398 | 0 | all |
| 2025 | 25,396 | 0 | all |
| 2026 | 2,994 | 0 | all |

All 53,788 rows passed the stricter validator. The JSON audit contains each source URL, capture time, retained filename, SHA-256 of the original bytes, row counts, count types, explicit zero counts, and resulting batch commitment. These are source-compatibility observations, not model-performance evidence. Reproduce by reading each retained Parquet asset with Polars, calling `prepare_snap_counts`, and comparing normalized `row_sha256` values against the old normalization; `stat_batch_sha256` must match the archived JSON for every season.

## Verification and operating checkpoint

Focused tests cover invalid input before any database transaction/write, a mixed valid/invalid batch, explicit zeros, unchanged row/batch commitments, duplicate identities, missing schema, empty data, regular-season scope, and the existing unidentified-row filter. Existing refresh failure/reporting and descriptive participation tests are also run.

Read-only production checkpoint at 16:59 UTC: last scan still `5c1bb697ca1f4cc5bb720aec6917e154` (14:21 UTC), 12/20 daily and 322/450 rolling credits reserved. Current pick boards remain empty; 241 prospective NFL forecasts remain unaccepted and unsettled. The frozen role candidate has ten distinct paired thresholds pending in one future game. No thresholds, model/evaluation versions, reserves, schedules, settlements, or frozen predictions are changed.

Next production evidence: let the regular free NFL refresh use the strict importer; check its `refresh:nfl` status and retained source commitments. Do not run a redundant refresh or extra quote collection solely to exercise the change. Reserved pregame capture stages begin CFB 2026-09-24 21:30 UTC and NFL 22:15 UTC. ATL/GB starts 2026-09-25 00:15 UTC; authenticate final outcomes before scoring pending prospective predictions. PR194 remains separately unapproved.

PR223 release `36022591472` previously deployed the participation and explanation corrections on `1458847`. Its 15:49 UTC live check confirmed 100 valid library forecasts with observed injury reports, no legacy comparison objects, and no obsolete on/off explanation bullets; desktop/mobile checks passed.
