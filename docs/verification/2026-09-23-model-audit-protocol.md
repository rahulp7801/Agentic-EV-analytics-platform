# End-to-end model audit and tuning protocol — 2026-09-23

This protocol is recorded before inspecting the new experiment's scores. The work is read-only against existing history and runs offline in memory. Persist aggregate diagnostics and fitted coefficients only, never raw database rows. No paid provider requests, cap changes, production probability changes, or wager execution are part of this experiment.

## Questions

1. Does the rolling-40 baseline remain calibrated when recent usage differs from older history?
2. Can recency and observed workload improve a forecast after chronological selection, compared with the deployed estimator and the already-frozen prior-80 shadow?
3. How much of the apparent sample is missing, conditional on participation, or correlated across markets/players/games?
4. Does the consumer see the exact quote, historical sample, limitations and a current-versus-recorded distinction?

## Frozen experiment

Use only prior dated observations, the production season floor (target season minus two), and at most 40 observations. Require at least 20 observations for a comparison. Generate half-point research thresholds from the 25th, 50th and 75th percentiles of the latest 10 prior stat observations, deduplicating equal thresholds. These are unpriced research questions; ROI and CLV are unavailable.

NFL relevance depends only on the latest five prior observations: mean passing attempts >=10, carries >=3, or targets >=2 for receiving yards/receptions. NBA requires mean prior-five minutes >=10. CFB retains observed stat-category rows and explicitly reports missing-category coverage; omitted categories are not invented zeroes. Target-game workload, team changes and results never enter features or relevance decisions.

Compare the deployed Jeffreys rolling-40 estimate with: (a) frozen symmetric prior strength 80, (b) game-recency half-life 16 with the Jeffreys prior, and (c) regularized logistic corrections using only prior history and workload. Logistic inputs are the base logit, recent-five and recent-ten hit-rate changes, standardized recent mean change, historical workload ratio, elapsed days since last observation, and share of earlier history from another team. Feature scaling is fitted on the training partition only. The fixed L2 penalties are 0.01 and 0.1 on the mean-loss objective; no expanded search follows evaluation.

| Sport | Fit | Select | Evaluate once |
| --- | --- | --- | --- |
| NFL | 2024 season | 2025-09-01 through 2025-10-31 | 2025-11-01 through 2026-02-14 |
| NBA | 2024 season | 2025-10-01 through 2025-12-31 | 2026-01-01 through 2026-04-30 |
| CFB | 2025 targets before 2025-11-01 | 2025-11-01 through 2025-11-30 | 2025-12-01 through 2026-09-22 |

Select one candidate per sport/prop using selection-period game-balanced Brier score; include the deployed baseline as a candidate and prefer it on ties. Each player/game has equal total threshold weight, and each game has equal total player weight. Report the selected candidate and baseline on exactly the same evaluation rows, log loss, calibration, counts, and paired uncertainty grouped separately by game and player. Training/selection/evaluation must each have at least 100 examples and 10 games to rank a fitted model. Smaller cohorts remain insufficient.

## Interpretation and promotion

These are retrospective temporal splits, not timestamped prospective forecasts. Prior NFL 2025 NGS and fixed-threshold studies and the NBA January 28 pilot have already examined some historical outcomes. Current database corrections can postdate target games. NBA historical provenance gaps and CFB missing-category selection remain limitations. The experiment can select a shadow candidate for later validation; it cannot establish a market edge or silently promote a model.

A candidate must improve both Brier and log loss, with both game- and player-cluster intervals below zero, to earn a further shadow evaluation. It must then be tested against contemporaneous exact no-vig sportsbook prices on later games under its own frozen model/policy version. Existing prospective edge requirements remain in force. Report coverage and negative results, and never weaken a qualification gate to fill the dashboard.

## End-to-end review scope

Source identities and provenance; absent versus zero stats; chronological cutoff and rolling samples; distribution/role drift; selection and multiple comparisons; pushes and interval interpretation; exact quote matching and age; availability evidence; risk reservation and immutable recording; final-stat settlement; duplicate and cluster accounting; API projection, caching, and consumer explanation.
