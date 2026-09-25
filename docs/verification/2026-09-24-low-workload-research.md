# Low-workload NFL model research — September 24, 2026

## Why this test

The first newly accepted raw NFL forecast, Skyy Moore receiving yards under 10.5, is outside both existing frozen shadow scopes: workload v1 reports `low_prior_workload`; role v1 reports `outside_source_scope`. It was captured after the board lock and remains absent from the current recorded consumer board. Its 80.4% model probability versus 49.4% matching no-vig market probability is a hypothesis to investigate, not verified betting advantage.

Read-only history inspection found 22 recorded games since 2024: three KC games, 17 SF games, and two current GB games. The last five recorded target counts are 1, 0, 0, 1, 3 (mean 1.0). Thus the existing workload threshold of two prior targets excludes this forecast as designed. Only two observed games describe the current team role. This inspection does not establish participation completeness or predict tonight's result.

## Separate exploratory protocol

`python -m sportsbet.quant.history_tuning --sport nfl --workload-scope low --output REPORT.json`

Default `eligible` behavior is preserved. The new opt-in scope requires 20–40 earlier observed category games, finite nonnegative prior workload, last-five average below the existing category minimum, and at least one positive workload observation in retained prior history. Target workload, target outcome, same-day and future rows cannot determine eligibility or features. Missing workload is excluded. CFB has no workload columns in this audit and rejects this scope before connecting to a database.

Training remains 2024; selection remains September–October 2025; evaluation remains November 2025–February 14, 2026. Existing prior-only research thresholds, five candidate specifications, equal-game/player/line weighting and separate game/player intervals remain intact. Evaluation-period history can update features only after its game date; coefficients and model selection do not use evaluation outcomes.

This is exploratory. The scope was motivated by an observed live forecast, existing evaluation outcomes have been inspected before, and the first pass included players with no prior category involvement. That first pass is retained in `2026-09-24-low-workload-initial-scope.json`. We then excluded players with no prior involvement because irrelevant structural zero outcomes dominated, e.g. non-passers in passing yards. Both attempts are disclosed; no untouched-test or confirmatory significance claim is made.

## Results

54,422 existing NFL rows (2023–2025); all core stat commitments verified. Historical workload values are **not** covered by those stat commitments. Corpus digest and full scores, fitted coefficients, counts, exclusions and limitations are retained in `2026-09-24-low-workload-nfl.json`.

Lower Brier is better. The selection period chose logistic correction L2=0.1 for all four categories.

| Category | Evaluation thresholds / games | Baseline Brier | Candidate Brier | Game-cluster 95% difference interval |
| --- | ---: | ---: | ---: | --- |
| Passing yards | 383 / 144 | .00818 | .00533 | [-.00467, -.00102] |
| Rushing yards | 1,813 / 150 | .11109 | .10403 | [-.01128, -.00285] |
| Receiving yards | 1,619 / 150 | .19130 | .18700 | [-.01070, +.00210] |
| Receptions | 1,264 / 150 | .18262 | .17726 | [-.01171, +.00100] |

Passing and rushing also have negative player-cluster Brier and both log-loss interval upper bounds. Receiving yards and receptions do not pass the existing research-support rule. In particular, this experiment does **not** justify a low-workload receiving candidate or validate the large Skyy Moore probability gap.

These are history-generated thresholds, not offered sportsbook prices. Rare trick-play passers, backup players and unoffered categories can remain in scope even after excluding zero prior involvement. Improved historical probability scores do not establish usable market edge. All report `promote` fields remain false; `shadow_research_supported` only identifies a historical research lead.

## Verification and next decision

61 targeted tests passed, covering original frozen shadow behavior, prior-only eligibility, exact threshold boundary, disjoint scopes, missing/nonfinite workload, future-outcome perturbation, and unsupported-scope rejection. No live model, frozen parameters, qualification gates, collector, quota, database records or customer recommendations changed. This audit made no provider requests and spent no credits or money.

Next model task: determine how many authenticated, pregame, paired **offered** passing/rushing thresholds actually fall in this scope. Reconstruct their prior workload without selecting on settled outcomes, report coverage and baseline agreement, and assess market-relative probabilities before deciding whether to freeze a separate prospective candidate. Do not broaden workload v1 or role v1 in place. Sparse offered-market coverage is a reason to defer a candidate, not to pool irrelevant historical categories.

Existing prospective evidence checkpoint remains September 25 at 04:30 UTC, or the first follow-up after authenticated final sources are available. Preserve pending outcomes if exact source identity and statistics cannot be verified. PR #194 remains excluded; quota limits and the staged reserve are unchanged.
