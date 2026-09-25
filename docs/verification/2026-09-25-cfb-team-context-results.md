# CFB team-context research result

The preregistered exploratory formula did not improve the existing CFB baseline. Preserve this negative result; do not tune its prior strength after seeing these scores or promote it into the scanner. This is a post-hoc research extension using previously examined historical outcomes and unpriced thresholds, not a prospective market test.

## Reproducibility

All 46,742 core-stat row commitments verify. The ordered input fingerprint exactly matches the September 23 history-tuning corpus. For the rushing and receiving-yard markets with prior evaluated reports, the complete baseline score objects reproduce exactly. The candidate uses the latest contiguous team segment in prior history; it never reads the target team or outcome for prediction. The original 20?40 observation rule, season floor, date cutoff, thresholds and missing-category behavior are retained.

## Evaluation period

Lower Brier is better. Games and players overlap between markets; these are research thresholds and are not independent wagers.

| Market | Games | Baseline Brier | Candidate Brier | Difference | Game-cluster 95% interval |
| --- | ---: | ---: | ---: | ---: | --- |
| pass_yds | 99 | 0.222176 | 0.223183 | +0.001007 | [-0.002013, +0.004027] |
| rush_yds | 233 | 0.226750 | 0.227643 | +0.000894 | [-0.000457, +0.002245] |
| rec_yds | 193 | 0.221991 | 0.222466 | +0.000475 | [-0.000976, +0.001926] |
| receptions | 193 | 0.235329 | 0.235406 | +0.000077 | [-0.001338, +0.001492] |

Brier and log-loss differences are positive in every evaluation market. Both game- and player-cluster intervals include zero in every case. The predeclared team-transition strata also have worse point estimates in all four markets. Full fit/select/evaluate partitions and both clusterings remain in the aggregate JSON; no favorable subgroup was selected after scoring.

## Verification and decision

28 focused research tests passed, including target/future mutation invariance, missing categories, date and season exclusions, return-to-team segmentation, exact baseline reconstruction, source/alias tampering and invalid inputs. The report always returns promote=false. Full CI results are recorded on the pull request.

The experiment strengthens the decision to preserve the production model and existing frozen candidates while their prospective outcomes accrue. It does not establish that all team-context models are ineffective, and it does not address missing participation categories, workload, or opponent effects. A future distinct hypothesis needs its own protocol and prospective validation; these reused results cannot serve as an untouched test.

Reproduce with `python -m sportsbet.quant.cfb_team_context --output <local-report.json>` using the existing read-only audit database configuration. The command reads a consistent hosted snapshot and writes aggregate diagnostics only. No quote collection, historical rewrite, database write, quota change, purchase, or bet is performed. PR #194 remains excluded.

The next authenticated-results checkpoint remains September 25 at 04:30 UTC, and the first recorded CFB picks have their separate September 26 at 04:30 UTC checkpoint. Both existing frozen prospective reports still require authenticated outcomes and the original promotion gates.
