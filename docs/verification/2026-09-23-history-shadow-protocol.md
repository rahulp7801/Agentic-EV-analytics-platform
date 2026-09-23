# Prospective workload shadow policy — 2026-09-23

Frozen before new prospective outcomes are collected, at 2026-09-23T15:36:55Z. This extends the end-to-end audit with predictions recorded alongside the existing scanner. It adds no provider requests, API budget, purchases, stakes, or consumer recommendations.

## Frozen candidates and input contract

Use exactly the five supported coefficient/scaler sets from `2026-09-23-history-tuning-results.json`: NBA points/rebounds/assists, NFL receiving yards/receptions. No refitting, calibration fit, blend search, or threshold optimization is permitted in this phase. Version `history-workload-shadow-v1`, policy `half-line-prior40-z8-v1`.

Only nonnegative half-point lines are supported. Integer lines remain unsupported because the experiment did not estimate push mass. Require an exact resolved player, the production exclusive event-date cutoff and season floor, 20–40 prior nonmissing stat observations, valid prior workload, and the original prior-five workload relevance floor. Require reconstructed rolling sample size, mean (within production rounding), and directional baseline probability to match the production forecast. A different matchup cohort is explicitly excluded.

Use scaler/coefficients without alteration. Exclude inputs whose standardized feature magnitude exceeds 8, invalid/missing history, and any history whose candidate Over probability increases across its half-point step-function thresholds. These are predeclared eligibility checks, not newly tuned parameters. Record skip reasons and retain their denominator. Require a source-verified fresh exact quote and pregame generation/recording after the frozen cutoff. Record feature values, current input digest, core-stat provenance counts, artifact hash, implementation hash and exact-offer binding in the immutable forecast payload. A digest does not prove older history was originally available before its historical games, and NBA missing historical row commitments remain disclosed.

## Collection and scoring

Reuse the existing scan's quotes and read bounded histories once per supported market/player batch from a read-only repeatable-read database snapshot. Candidate errors must not change production probabilities, eligibility, exposure reservation, settlement or public picks. The shadow has no acceptance or stake policy. Its payload is internal and omitted by public projections.

Grade using the parent forecast's existing exact final-event/stat/source verification. Select the earliest shadow attempt per sport, game, player ID, market and line before examining status or result; prefer Over on a same-capture side tie and retain explicit unavailable attempts. Deduplicate complementary sides, repeat scans and alternate sportsbooks. Include all baseline acceptance states. Pair only authenticated same-book, same-time opposite prices; report missing pairs rather than approximate a market baseline.

Evaluate each market separately. Give each game equal weight, each player/game equal weight, and each retained line equal weight. Report candidate, production and market Brier/log loss on the identical decided paired cohort, with candidate-minus-baseline and candidate-minus-market intervals grouped separately by game and player. Report attempted, skipped, valid, pending, unpaired and decided counts. Unknown/invalid settlements remain pending. Do not treat repeated alternate lines as independent games.

At least 50 paired games and negative upper 95% bounds for both metrics against both comparators under both groupings are required to label predictive evidence supported. Fewer games are insufficient; crossing intervals mean evidence not demonstrated. This is a research milestone only. No ROI, candidate recommendations, or betting-edge claim follows: the existing strategy protocol still requires a separately frozen acceptance policy and 100 decided recommendations across 30 games with a positive ROI lower bound. All status reads are descriptive checkpoints; no automatic promotion or repeated-look significance claim.

## Operational verification

Verify parity with the frozen historical feature formula and artifacts; future/same-day exclusion; exact quote and chronology checks; integer and outlier rejection; complement and monotonicity; immutable storage; zero effect on production signals and exposure; graceful database failures; packaging in the actual worker image; and real disposable PostgreSQL history queries. Confirm deployed collection after the next normally scheduled scan without issuing a paid refresh or backfilling historical shadow forecasts.
