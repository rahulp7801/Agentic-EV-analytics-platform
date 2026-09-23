# End-to-end model audit and tuning — 2026-09-23

## Decision

Keep the current production probability version while freezing five fitted candidates for prospective shadow validation: NBA points, rebounds, assists; NFL receiving yards and receptions. Fix the identified output and settlement defects now. The experiment found repeatable improvements over rolling history on later historical periods, but has not established an advantage over sportsbook prices. CFB and NFL passing/rushing do not meet the frozen statistical support rule.

This audit used 154,121 existing historical rows in read-only transactions, plus the existing priced prediction ledger. No new odds requests, paid data, purchases, wagers, or production model promotion were performed. Only aggregate results, input hashes, and fitted coefficients are retained in this change.

## Reproduction and artifacts

- [Protocol recorded before scores](2026-09-23-model-audit-protocol.md).
- [Full tuning results and fitted coefficients](2026-09-23-history-tuning-results.json).
- [Exact-price ledger audit](2026-09-23-priced-model-audit.json).
- Implementation: `src/sportsbet/quant/history_tuning.py`.
- Run: `python -m sportsbet.quant.history_tuning --sport all --output <aggregate-report.json>` with the existing database configuration. The command opens a read-only repeatable-read transaction and never writes raw history.

The report commits each exact in-memory input corpus to SHA-256. Its `source_sha256` identifies the original evaluated implementation; `provenance_recheck` separately records the identifier-normalization correction. That correction was applied against an identical CFB input hash and changed only provenance diagnostics, not scores, model selection, or coefficients. No evaluation-period refit or expanded parameter search followed these results.

## What the production algorithm currently does

The model estimates an exact player's Over/Under probability from up to 40 strictly prior games, retaining the production season floor. It applies a Jeffreys half-count prior and preserves observed push mass. NBA first attempts a narrow opponent/venue sample and falls back to rolling history when coverage is insufficient. This study evaluates that rolling estimator, not the entire matchup-selection or injury-filter policy.

Admission requires source-backed exact player/event/market/side/line/price identity, sufficient history, current availability, a fresh quote, the interval floor above push-adjusted break-even, and available risk capacity. A large model probability alone does not meet these conditions. Context evidence is displayed, but most context does not change the deployed probability. Acute teammate absences can block the unadjusted model; no validated teammate-absence effect is currently estimated.

The main statistical weakness is that a 40-game historical frequency can lag changing opportunity: minutes, targets, carries, passing attempts, team changes, and offseason gaps. A Wilson interval describes binomial sampling uncertainty; it does not cover all uncertainty from changing role, dependent observations, opponent strength, source corrections, or searching many lines. The UI's historical sample interval must not be read as a calibrated guarantee about the next game. See the [interval method documentation](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html).

## Tuning experiment

The feature correction uses the base probability plus prior-five/prior-ten hit rates, a standardized recent mean change, recent versus longer-term workload, time since the last observation, and earlier-team history share. No target-game workload, target result, or target team enters the feature values. Scaling and coefficients are fitted on the fit partition only; selection chooses among the five predeclared candidates before the final temporal evaluation. This follows the [training-only preprocessing principle](https://scikit-learn.org/stable/common_pitfalls.html).

Half-point thresholds are derived from each player's prior history. They are research thresholds, not observed bookmaker offers. Each game receives equal total weight, then each player within the game, then each distinct threshold. Paired uncertainty is calculated separately by game and player; it does not fully capture all dependence across both groupings. Historical outcomes have appeared in earlier project research, and the current archive may include later corrections. These are retrospective temporal tests, not untouched prospective trials.

Lower Brier score is better. Relative improvement below is a reduction in prediction error, not an increase in profit or win rate.

| Sport / market | Evaluation player-games | Distinct games | Selected candidate | Baseline Brier | Candidate Brier | Relative improvement | Meets shadow support rule |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| NBA points | 13,464 | 734 | Logistic, L2 0.01 | 0.22548 | 0.21666 | 3.91% | Yes |
| NBA rebounds | 13,464 | 734 | Logistic, L2 0.01 | 0.21953 | 0.21262 | 3.15% | Yes |
| NBA assists | 13,464 | 734 | Logistic, L2 0.01 | 0.22014 | 0.21322 | 3.14% | Yes |
| NFL passing yards | 220 | 140 | Half-life 16 | 0.22226 | 0.21865 | 1.62% | No |
| NFL rushing yards | 563 | 150 | Logistic, L2 0.1 | 0.22154 | 0.21278 | 3.96% | No |
| NFL receiving yards | 1,365 | 150 | Logistic, L2 0.01 | 0.22714 | 0.21724 | 4.36% | Yes |
| NFL receptions | 1,365 | 150 | Logistic, L2 0.1 | 0.22308 | 0.21036 | 5.70% | Yes |
| CFB rushing yards | 469 | 233 | Half-life 16 | 0.22675 | 0.22300 | 1.65% | No |
| CFB receiving yards | 447 | 193 | Half-life 16 | 0.22199 | 0.22010 | 0.85% | No |

CFB passing and receptions remain insufficient: their fit partitions contain only 75 and 99 threshold examples, respectively, below the predeclared 100 minimum. The floor was not changed after seeing the sample. Repeated thresholds and markets share outcomes; row counts must not be interpreted as independent games.

The five supported candidates improve both Brier and log loss with both game- and player-grouped 95% intervals below zero. NFL rushing and CFB rushing improve game-grouped scores but their player-grouped intervals include zero. All nine evaluated candidate point estimates improve; this does not make all nine reliable improvements.

### Nuances that matter for model design

- Workload is a promising input. In the predeclared role-drift subset, NBA points Brier changes from 0.23130 to 0.21416 and NFL receptions from 0.23171 to 0.20694. These are descriptive subset results, not independently selected production policies or proof of a causal workload effect.
- NBA row-weighted calibration error decreases from 0.03477 to 0.01076 for points. NFL receptions decreases from 0.07025 to 0.04944; meaningful residual miscalibration remains. Bin-based calibration error depends on bins and cohort composition and is not the selection criterion.
- The combined feature correction is supported; individual feature contributions are not established by this experiment. Coefficients on correlated inputs should not be interpreted as causal effects.
- Simply increasing shrinkage or overweighting the recent five games is not a universal solution. The best candidate differs by sport and market. Older prior-80 research still trails the exact-price market baseline in the current NFL ledger.
- The relevance screen uses prior workload, not target-game participation or the offered-player universe. Missing outcome rows cannot reveal DNPs or bookmaker void rules. This experiment evaluates observed participants, not every potential offer.
- Integer-line push behavior, monotonicity across alternate lines, out-of-distribution inputs, and uncertainty for the fitted correction require separate validation before consumer use. The half-line experiment supplies neither a fitted-model confidence interval nor a live stake policy.

## Actual priced results

The current NFL ledger contains 5,208 decided earliest eligible selections from only 16 games. On the 4,421 selections with exact same-book opposite-side prices, the production model Brier is **0.26528**, versus **0.24503** for no-vig market probabilities. The paired difference is +0.02025, with game-bootstrap 95% interval +0.00457 to +0.03918; lower is better. The prior-80 shadow scores 0.24891 on those same paired selections.

The hypothetical equal-stake replay of all 5,208 decided selections is -5.31%. This is a diagnostic across all forecasts, including rejected ones. It is not the consumer recommendation strategy. The actual recommendation cohort has only three settled selections from one game: hypothetical equal-stake ROI -20%, recorded-stake replay -55.09%. Neither is executed account profit. One game is far too small to estimate a stable strategy return.

These priced figures demonstrate why generating more qualified labels would not establish an edge. The new historical correction has not yet been scored on future contemporaneous offers. The project must retain the denominator of rejected forecasts as well as accepted picks and compare models on exactly matching offers and final outcomes.

## Data and output trace

| Stage | Finding | Action / status |
| --- | --- | --- |
| NFL history | 54,422 rows; all core-stat row commitments verify | Workload columns are not included in those legacy core-stat hashes; the study input hash covers the present corpus but cannot prove historical availability |
| NBA history | 52,957 rows; no row commitments present | Suitable for limited retrospective exploration; cannot present this archive as fully source-verified training evidence |
| CFB history | 46,742 rows; all core-stat commitments verify after numeric event-ID reconstruction | Preserve source hash semantics across VARCHAR storage |
| Missing CFB categories | Passing absent in 40,420 rows; rushing in 23,275; receiving/receptions in 14,474 | Keep unknown categories missing; no fabricated zeros or DNP outcomes |
| Model execution | One thrown or returned selection error could discard valid neighboring forecasts | Isolate failed selections, report partial coverage, retain all gates; all-selection failure still fails the event |
| Quote age | Quotes expire much sooner than regular scan cadence | A historical recorded pick is distinct from a currently executable fresh quote; no quote recapture or budget change in this work |
| Availability | Current evidence and acute absence gates are separate from probability estimation | Do not imply the model has learned injury adjustments |
| Risk and recording | Immutable forecast identity and shared exposure limits govern acceptance | Failed selections never reserve risk or acquire invented probabilities |
| CFB settlement | Query bound numeric event ID to VARCHAR; proof reconstruction also expected an integer | Bind the stored text ID, reconstruct canonical numeric ID only for authenticated evidence, retain exact event/player identity |
| Dashboard pick list | Validation against the current clock rejected a previously valid snapshot when a pick crossed its lock/start time | Validate original state at snapshot time, filter started games, preserve unrelated upcoming records; do not invent lock confirmation or settlements |
| Dashboard polling | Research suggestions refresh independently; retained current picks could age in client cache | Also filter started retained picks locally before display |
| Public explanation | History panel shows a limited prior-game excerpt, not necessarily all model observations | Keep this distinction explicit; the interval describes historical sampling, not a validated betting edge |

The settlement regression now uses both text and integer SQLite identities and includes a disposable PostgreSQL test against the migrated VARCHAR schema. Source tampering still fails verification. The live database was not modified by this audit.

## Consumer contract

1. A current qualified pick must have a matching fresh quote, exact game/player/market identity, a supported estimate, availability evidence, and passed admission/risk checks.
2. A retained pick must show its capture time, recorded price, and recorded/confirmed-lock status. Clock passage alone cannot confirm a lock. Started picks disappear from the upcoming list while final evidence is pending.
3. A research suggestion may explain model-versus-price disagreement but cannot imply qualification, executable odds, calibrated confidence, or guaranteed return.
4. A final result requires exact completed-event identity, the observed stat category, source commitment verification, and reproducible grading. Missing evidence remains pending.
5. Daily coverage is a pipeline objective. A daily minimum of qualified picks cannot be promised across offseason sports, missing offers, stale evidence, and models that fail admission.

## Next promotion gate

Freeze the five supported feature/scaler/coefficient sets in this result artifact. Before any live probability replacement, implement an exact-offer shadow adapter with parity checks for cutoff, player identity, workload, line semantics and model hash; record predictions before kickoff alongside the production version without changing acceptance or stake. Reject unsupported inputs rather than substituting defaults. Collect later final outcomes and evaluate both models against contemporaneous same-book no-vig prices.

Use the existing [prospective edge protocol](2026-09-23-prospective-edge-protocol.md): at least 50 paired games with the upper bound of the model-minus-market Brier interval below zero, plus 100 decided accepted selections across at least 30 games with ROI lower bound above zero before claiming measurable strategy edge. The new candidate needs its own frozen model/policy version and forward cutoff. Better retrospective scores earn this next experiment; they do not bypass it.

## Verification

Focused backend regression suites passed: 49 scan/history tests and 45 settlement/provenance/history tests. All 159 frontend tests passed; ESLint and TypeScript checks passed. Full backend and hosted PostgreSQL/build/security CI results are recorded in the associated pull request. No live picks were manufactured to validate the UI.
