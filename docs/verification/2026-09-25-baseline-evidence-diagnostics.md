# Baseline evidence diagnostics and priced low-workload evaluation

Observed September 25, 2026 UTC. Follow-up to PR #228.

## Root cause established

Every one of the 69 low-workload thresholds labelled `baseline_reconstruction_mismatch` in the first audit matches the recorded sample count and model probability when reconstructed. All 69 lack `model_mean_stat`, which older ledger records did not store. Counts: 19 rushing, 34 receiving yards, 16 receptions. This establishes a metadata gap, **not** a contradictory probability or a proven source correction.

The audit used a missing-value sentinel in a numerical comparison. It now distinguishes complete agreement, partial agreement with only the mean missing, insufficient other metadata, and actual invalid/conflicting fields. Missing metadata remains missing; neither the original forecast nor prospective evaluators are changed. Conflicting probabilities and samples remain conflicts even when a mean is absent.

`baseline_reconstruction.py` is research-only. Its diagnostic cannot grant prospective eligibility. Frozen workload/role models, inputs, source/chronology checks, promotion rules, and live model gates are unchanged.

## Corrected offered-market coverage

The v2 output retains individual prediction IDs, reconstructed features and evidence reasons for replay. Earliest game/player/market/line is fixed before checks; complementary sides and books are not independent observations. Source-eligible quote pairs must agree with committed matching-price evidence when both exist.

| Market | Complete paired thresholds / games | Partial paired thresholds / games | Missing-mean records without a matching price |
| --- | ---: | ---: | ---: |
| Passing yards | 0 / 0 | 0 / 0 | 0 |
| Rushing yards | 2 / 1 | 12 / 9 | 7 |
| Receiving yards | 7 / 2 | 24 / 5 | 10 |
| Receptions | 2 / 1 | 5 / 4 | 11 |

Artifacts: `2026-09-25-low-workload-offers-v2.json`; runner `2026-09-24-low-workload-offers.py`. The original v1 report remains unchanged. Partial agreement does not authenticate the original mean, workload values, or a forecast-time copy of the reconstructed history.

## Retrospective comparison against real prices

Using the already selected L2=0.1 corrections from the historical low-workload experiment, we scored these fixed cohorts against authenticated settlement evidence and matching market prices. Candidates were not refitted. The scoring runner reloads exact forecast bindings and matching prices, rejects duplicate thresholds and altered bindings, reverses under-side outcomes correctly, and excludes pending/unverified results. Complete and partial metadata strata are reported separately. Equal game weight, then equal player/game and line weight, is used for all three models.

| Partial-metadata market | Decided thresholds / games | Existing model Brier | Candidate Brier | Matching market Brier | Candidate minus market 95% game interval |
| --- | ---: | ---: | ---: | ---: | --- |
| Rushing yards | 12 / 9 | .24447 | .24697 | .26291 | [-.12616, +.09428] |
| Receiving yards | 24 / 5 | .31096 | .37686 | .25360 | [-.02328, +.26979] |
| Receptions | 5 / 4 | .14691 | .16943 | .15868 | [-.20512, +.22664] |

Lower Brier is better. Rushing's candidate point estimate is better than market but worse than the existing model; both its Brier and log-loss intervals against market and existing model cross zero. The receiving candidates have worse point estimates than both comparators. The complete-metadata stratum has only one settled receiving-yards threshold/game (candidate .41747 versus market .25); remaining complete pairs are unresolved and retained as pending, not losses or zeros.

**Decision: do not promote or freeze a low-workload correction from these results.** The actual offered-market test does not substantiate improvement over the existing model or an edge. This is small, repeatedly examined retrospective data; current history can reflect later source corrections, and core stat hashes do not commit workload values. No profitability, CLV, or prospective-edge claim follows. The candidate is also not validated as a full monotonic production distribution across all thresholds.

Artifacts: `2026-09-25-low-workload-priced-exploration.py` and its JSON report, including game/player intervals, log loss, exclusions and source artifact digests. All `promote` fields remain false.

## Verification and continuation

- 56 targeted baseline-diagnostic and frozen-shadow tests passed.
- 21 targeted diagnostic, exact-price and retrospective-scoring tests passed. Coverage includes missing versus conflicting evidence, partial/full separation, pending outcomes, under inversion, duplicate thresholds and changed forecast/market bindings.
- Queries were read-only. No odds collection, API quota use, card use, purchases, bets, or database writes.
- Existing broad receiving workload and exact-roster role experiments remain frozen and active. Next prospective evidence checkpoint: September 25, 04:30 UTC, or the first follow-up after authenticated finals. Do not settle before exact final source evidence exists.
- Independent operational task remains the intermittent NFL game-log endpoint 503 documented in PR #227. Its expensive view query is a measured lead; the root cause still needs verification. PR #194 stays excluded.
