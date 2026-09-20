# Free NFL Next Gen Stats plan

## Decision

Use the free nflverse Next Gen Stats release through `nflreadpy`. The upstream
project publishes passing, receiving, and rushing files sourced from NFL Next Gen
Stats, and polls the data daily during the NFL season. No API key is required.

- [nflverse data automation and licensing](https://github.com/nflverse/nflverse-data)
- [nflverse NGS collection project](https://github.com/nflverse/ngs-data)
- [`nflreadpy.load_nextgen_stats`](https://github.com/nflverse/nflreadpy/blob/main/src/nflreadpy/load_nextgen_stats.py)

This source applies to NFL players only. It does not provide NBA or CFB tracking
data and must not be presented as coverage for those leagues.

## Current code and release blocker

The repository already contains `sportsbet.ingestion.ngs`, the `ngs_stats` table,
and a kinematic graph node. They are not production-ready:

- ingestion appends every download, so retries can duplicate player/week rows;
- the table retains no source URL, retrieval time, release digest, or row digest;
- sparse upstream schemas are silently accepted;
- the scheduled refresh does not load NGS data;
- `run_matchup_query` accepts a target week but averages the entire season;
- the optional receiving adjustment adds a fixed five percentage points from a
  hard-coded separation threshold and discards its uncertainty interval.

The season-wide query is future-data leakage for any forecast before the end of
that season. `EXPERIMENTAL_PROBABILITY_ADJUSTMENTS` must remain disabled until the
query and evaluation contract below are complete.

## Next release scope

### 1. Reproducible ingestion

Add a migration with a unique key on
`(player_gsis_id, season, week, stat_type)`, then replace append-only writes with
an idempotent upsert. Require identity, season, week, stat type, and the documented
metric columns for each stat type. Reject duplicate keys, non-finite values, and
out-of-range weeks before writing.

Retain the provider, canonical release URL, retrieval timestamp, raw file SHA-256,
and normalized row SHA-256. Cache the nflverse files on the worker filesystem so a
daily retry does not redownload an unchanged release. Refresh the current and prior
season during the NFL history job; historical backfills remain manual.

### 2. Pregame evidence boundary

Every query must filter to rows known before the target game's kickoff. For a
regular-season Week N forecast, aggregate only weeks `< N`; postseason handling
must use an ordered game timestamp rather than assuming a week number is unique.
Exclude upstream `week == 0` season summaries because they incorporate the full
regular season.

Join by verified GSIS ID. Missing or ambiguous identity yields no NGS evidence.
The public response may expose only the whitelisted metric, sample weeks, cutoff,
source URL, capture time, and digest. It must not expose database keys or raw
provider payloads.

The first release should show these as sourced context:

- passing: average time to throw, intended/completed air yards, aggressiveness;
- receiving: average separation, cushion, YAC over expected;
- rushing: efficiency, box rate, rush yards over expected, time to line of scrimmage.

No metric changes a pick probability in this stage.

### 3. Validation before model use

Build an expanding-window comparison using the same game-time cutoff as the live
scanner. Compare the existing model with candidate NGS features on untouched game
clusters. Report coverage, missingness, Brier score, log loss, calibration error,
and their game-cluster intervals. A feature can affect probability only when it
improves Brier score and log loss without degrading calibration on an untouched
evaluation season.

Remove the fixed separation threshold and fixed probability boost. If no candidate
passes the evaluation contract, retain NGS as explanatory evidence only. Do not
claim a win-rate, ROI, or pricing improvement from tracking metrics alone.

### 4. Operations and scale

The daily job should download each stat-type asset at most once, hash it, and skip
unchanged content. Batch one transaction per stat type, publish counts and coverage,
and fail the NGS portion closed without blocking the base model. Alert on upstream
schema changes, digest changes with zero rows, duplicate keys, and current-week lag.

## Release acceptance

- two identical ingestions produce identical rows and digests;
- a Week N query cannot read Week N or later rows;
- season-summary rows cannot enter a pregame feature;
- a bad schema or ambiguous player ID produces no evidence;
- the live dashboard labels the source, cutoff, sample, and freshness;
- base recommendations are unchanged while the feature is evidence-only;
- PostgreSQL integration, frontend contract, security, and production browser
  checks pass before the release is tagged.
