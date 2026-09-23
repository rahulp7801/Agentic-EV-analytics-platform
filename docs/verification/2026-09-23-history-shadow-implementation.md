# Prospective workload shadow implementation — 2026-09-23

## What is enabled

The existing scan now computes an untraded `history-workload-shadow-v1` probability for supported exact offers, alongside `empirical-jeffreys-v4`. The five frozen candidates are NBA points/rebounds/assists and NFL receiving yards/receptions. CFB and the other NFL markets retain explicit unsupported status. No production probability, admission rule, stake, provider request, schedule or API allowance is changed.

The [policy](2026-09-23-history-shadow-protocol.md) was committed before this implementation. Coefficients are copied exactly from the prior audit into a Python artifact packaged with the worker; nothing is downloaded or fitted at runtime. The artifact has a fixed SHA-256, and implementation hashes normalize source line endings across Windows and Linux.

## Capture contract

- Only source-verified half-point offers captured after `2026-09-23T15:36:55Z`, before kickoff, within five minutes of the exact quote are eligible.
- Bounded histories are fetched in a read-only repeatable-read transaction alongside existing model work. Queries have a four-second timeout, with a five-second total research collection budget and no provider calls. Each player/market contributes at most 40 rows.
- The exact player, exclusive game-date cutoff, season range, workload relevance, sample count, baseline probability and historical mean must match. Missing stats are never zero-filled. Integer lines, implausible input types, source mismatches, standardized feature magnitudes above eight, and nonmonotone candidate curves are excluded.
- Each predicted record retains the seven feature values, input-history digest, available core-stat commitment counts, exact-offer binding, artifact hash and implementation hash. NBA legacy commitment gaps and unhashed workload fields are disclosed; hashes do not retrospectively establish original source availability.
- The ledger assigns `history_shadow_recorded_at` during insertion. Delayed, invalid, or post-kickoff candidate records are downgraded to unavailable while preserving the primary forecast. Existing records are immutable; no historical predictions are backfilled.
- Candidate failures are isolated. The scanner's `history_shadow.inference_counts` describes computed results; the ledger report counts persisted and validated records. Those can differ if a quote expires before recording.
- No candidate acceptance/stake is generated, and candidate features/probabilities are omitted from public signal projections. The current consumer model remains v4.

## Evaluation and operations

The same exact final-event/stat/source settlement evidence grades both probabilities. Evaluation retains the earliest attempted capture per game, player ID, market and line before checking candidate status or outcome. Complementary sides, repeat scans and books cannot multiply the denominator. Only source-verified same-book, same-time opposite prices supply the no-vig market baseline.

Each market reports attempts, unavailability reasons, valid forecasts, pending outcomes, absent market pairs and paired settled counts. Brier and log loss use equal game weight, then equal player/game weight, then equal line weight. Candidate-minus-production and candidate-minus-market uncertainty is reported separately by game and player. The frozen 50-game research gate cannot automatically promote a model or establish profitability; this candidate has no wager policy or ROI.

Both the existing scan and post-settlement daily phases publish aggregate `shadow-validation:nba`, `shadow-validation:nfl`, and `shadow-validation:cfb` snapshots. Their failures do not fail production forecasting or settlement. The usual scheduled collector supplies future offers under existing quota rules; this change does not force an extra refresh.

Read-only audit command:

```powershell
python -m sportsbet.quant.history_shadow_audit --sport all --output .local/history-shadow-audit.json
```

The command reads existing ledger records and saves aggregate diagnostics only. `HISTORY_SHADOW_ENABLED=false` disables future collection without changing the production model or erasing prior trial records.

## Activation evidence

A read-only pre-activation check found **zero** shadow attempts in all three sports. NBA/NFL correctly report collecting with insufficient data; CFB reports no frozen candidate. This is a prospective starting point, not a backfilled performance claim.

Focused suites passed 95 tests covering frozen artifact parity, the original feature formula, source/cutoff rejection, complement/monotonicity, immutable recording, grouping/scoring, and unchanged primary output when collection is enabled or its history read fails. Additional full-suite, real PostgreSQL and packaged-worker verification runs in the pull request. No purchases, extra odds requests or wagers are part of this phase.
