# Free NFL Next Gen Stats evidence contract

## Decision

Use the free nflverse Next Gen Stats release assets directly. The upstream project
publishes passing, receiving, and rushing parquet files sourced from NFL Next Gen
Stats, and polls the data daily during the NFL season. No API key is required.

- [nflverse data automation and licensing](https://github.com/nflverse/nflverse-data)
- [nflverse NGS collection project](https://github.com/nflverse/ngs-data)

This source applies to NFL players only. It does not provide NBA or CFB tracking
data and must not be presented as coverage for those leagues.

## Implemented data boundary

Migration 0029 replaces unverifiable legacy rows with a private evidence table.
The worker downloads the three bounded nflverse parquet assets over allowlisted
HTTPS redirects, caches their raw bytes for 20 hours, and stores the exact asset
SHA-256 plus a normalized row SHA-256. Every documented source column is required;
invalid schemas, duplicate weekly identities, non-finite metrics, invalid counts,
season summaries, and unidentified players fail closed.

Refreshes are idempotent on `(player_gsis_id, season, week, stat_type)`. An unchanged
asset and exact normalized row-hash set causes no writes. Daily NFL history refreshes load the
current and prior season; a backfill loads its full requested window while still
downloading each stat-type asset only once. NGS is optional context, so an upstream
failure is recorded without disabling the independently sourced base model.

The former season-wide matchup query now filters both receiver and quarterback rows
to `week < target_week`. Published evidence independently resolves the exact target
week from the schedule and uses at most the eight latest weekly rows from the target
and prior season. It is joined only by exact GSIS player ID.

## Published evidence

The public response exposes only the whitelisted metrics, sample weeks, exclusive
cutoff, source URL, capture time, and digest. Browser validation strips malformed
or unexpected fields. The explanation panel shows:

- passing: average time to throw, intended/completed air yards, aggressiveness;
- receiving: average separation, cushion, YAC over expected;
- rushing: efficiency, box rate, rush yards over expected, time to line of scrimmage.

Every response carries `probability_adjusted: false`. No metric changes a pick
probability or recommendation gate in this stage.

## Required validation before model use

Build a fixed-fit walk-forward comparison using the same game-time cutoff and
rolling history limits as the live scanner. Compare the existing model with
candidate NGS features on untouched game clusters. Report coverage, missingness,
Brier score, log loss, calibration error, and their game-cluster intervals. A
feature can affect probability only when it improves Brier score and log loss
without degrading calibration on an untouched evaluation season.

Remove the fixed separation threshold and fixed probability boost. If no candidate
passes the evaluation contract, retain NGS as explanatory evidence only. Do not
claim a win-rate, ROI, or pricing improvement from tracking metrics alone.

The reproducible evaluator is `python -m sportsbet.quant.ngs_ablation`. It builds
the same 20-to-40-game Jeffreys baseline at an exclusive game cutoff, derives a
half-point rolling-median research threshold without using a historical price, and
adds at most eight prior NGS weeks. Candidate coefficients and standardization are
fit on the training season only. The following season remains untouched until the
single final comparison. Promotion additionally requires the paired 95% whole-game
cluster intervals for Brier score and log loss to be below zero and calibration not
to worsen. The command never changes the live model flag.

The first completed evaluation is recorded in
[`verification/ngs-ablation-2025.md`](verification/ngs-ablation-2025.md).

Example:

```powershell
uv run python -m sportsbet.quant.ngs_ablation --train-season 2024 `
  --evaluation-season 2025 --output .local/ngs-ablation-2025.json
```

## Operations and scale

The daily job downloads each stat-type asset at most once per cache window, hashes
it, skips unchanged database content, and writes each season/stat type in one
transaction. Coverage reports include rows, skipped identities, cache state, source
URL, and hashes. No new environment secret or paid API is required.

## Release acceptance

- two identical ingestions produce identical rows and digests;
- a Week N query cannot read Week N or later rows;
- season-summary rows cannot enter a pregame feature;
- a bad schema or ambiguous player ID produces no evidence;
- the dashboard labels the source, cutoff, sample, and capture time;
- base recommendations are unchanged while the feature is evidence-only;
- PostgreSQL integration, frontend contract, security, and production browser
  checks pass before the release is tagged.
