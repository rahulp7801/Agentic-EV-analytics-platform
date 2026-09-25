# CFB last-observed-team context: exploratory protocol

Recorded before computing this experiment's scores. Existing history, recency, and role-drift results have already been examined; this is a post-hoc research extension on reused data, not an untouched holdout or prospective evidence.

## Question and fixed candidate

Does a player's latest observed team context improve the empirical distribution when earlier observations came from another team? Use the exact existing CFB research cohort: source-committed category observations, strictly earlier game dates, target-season minus two floor, 20?40 observations, and the existing prior-ten-game quartile half-point thresholds. Missing categories remain unknown. Do not use the target game's team, workload, or outcome to choose the current context.

The current context is the contiguous suffix of prior observations with the same team as the last prior observation. A return to an older team starts a new segment. Split the retained history into this suffix and its earlier prefix. If the prefix is empty, use the unchanged Jeffreys baseline. Otherwise, use `(current_hits + 20 * older_Jeffreys_probability) / (current_count + 20)`. Fix prior strength at 20 before scoring, borrowing the existing role-history research constant; do not search alternatives after results. This is not the existing frozen NFL role model and must not alter it.

## Evaluation

Reuse the original CFB calendar partitions (2025 before November fit, November select, December through September 22 evaluate) solely for reporting. No fitting or candidate selection occurs in this experiment. Score the whole eligible cohort and a predeclared transition stratum whose retained history contains an earlier team segment. Compare game-balanced Brier and log loss on identical rows, with game- and player-cluster intervals. Report all four markets, all three partitions, coverage, and negative findings. No post-result filter, threshold change, or expanded candidate search.

Source commitments and exact baseline/sample reconstruction must validate before scoring. Keep raw database rows in memory; write aggregate diagnostics and the input hash only. Unknown or invalid team identities must not be replaced by the target team's identity. Historical provider corrections can postdate games; hashes do not establish pregame source availability. Stat-category histories are not a complete participation census, and the latest observed team may lag a transfer with no recorded category appearance.

## Decision boundary

This experiment is descriptive. Every report returns `promote=false`; it creates no forward forecasts, qualified picks, stakes, ROI, or market-edge claim. Existing frozen evaluation versions and promotion requirements remain intact. Any later candidate needs separate source/chronology review and genuinely prospective exact-price evaluation under its own version. No old offers may be backfilled. No collection, quota change, paid service, or result write is required.
