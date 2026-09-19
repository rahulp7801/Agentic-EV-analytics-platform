# Prop probability model and validation

The current scanner cohort is `empirical-jeffreys-v4`. NBA and NFL prop scans use
the same finite-sample probability contract when per-game outcomes are available.
For `o` Overs, `u` Unders and `p` pushes, the model keeps the observed push mass
`p / n`. Conditional on a decided outcome, its next-outcome Over estimate is:

```text
(o + 1/2) / (o + u + 1)
```

The unconditional Over estimate multiplies that value by `(o + u) / n`; Under is
the remaining mass. A Wilson interval is calculated on the decided sample and
scaled by the same non-push mass. Samples with no decided outcomes are unavailable.
This prevents a finite history from producing an unjustified exact 0% or 100%
forecast and keeps Over + Under + push equal to one.

The half-count estimator is the Bernoulli form of the Krichevsky-Trofimov estimator
and the posterior predictive mean under a fixed Jeffreys `Beta(1/2, 1/2)` prior.
It has no fitted sports-specific parameter. See
[Krichevsky and Trofimov (1981)](https://doi.org/10.1109/TIT.1981.1056331).
Brier score and log loss remain the evaluation metrics because they are strictly
proper scoring rules; see [Gneiting and Raftery (2007)](https://doi.org/10.1198/016214506000001437).

## Signal admission and sizing

A positive point estimate is insufficient for a recommendation. The LangGraph
decision node requires the requested side's 95% interval lower bound to exceed
the quote's break-even win probability after accounting for observed push mass.
Missing, non-finite, out-of-range, or overlapping bounds return an audited gate
reason and no signal. Every evaluated selection retains its sample size and
directional interval in the prediction ledger, including rejected estimates.

For Under, the Over interval `[lo, hi]` is complemented within non-push mass as
`[1 - push - hi, 1 - push - lo]`. This retains `Over + Under + push = 1` even on
integer lines. Fractional Kelly sizing uses the admitted side's lower bound,
conditional on a decided result, rather than the point estimate. The displayed
expected return continues to use the point estimate and is not a guaranteed
return. Interval admission is a conservative uncertainty screen; it does not
establish calibration, independence, market-rule equivalence, fills, or profit.

## Public signal boundary

The dashboard API accepts a signal only when its event, player, sport, prop,
direction, line, sportsbook, integer American price, model cohort, sample fields,
and quote/game timestamps are present and valid. It recomputes implied probability,
edge, expected return, uncertainty, gating, and stake eligibility at the boundary.
Unexpected worker fields are omitted. Invalid records are excluded and counted as
`invalid_signals`; the UI does not fill missing values with a plausible sport,
market, direction, venue, price, probability, line, or stake. PrizePicks projections
cannot enter this priced-signal response until a complete entry payout is captured.

## NBA matchup identity

The NBA LangGraph context node assigns home/away, opponent and rest context only
when the player's latest gamelog team is one of the two canonical teams in the
scheduled event. A missing player ID, missing prior gamelog, or third-team record
returns no matchup context. The as-of base model can still evaluate available
player history, but it receives no invented venue or opponent filter.

The production scanner first evaluates verified same-opponent and same-venue
history. If matchup or availability filters leave fewer than the 20 observations
required by the signal gate, v4 removes only those narrow filters and re-evaluates
the same player, line, exclusive target-date cutoff, and rolling-game limit. It does
not blend the sparse matchup estimate into the fallback. A hosted history audit of
5,179 recent player-game targets found no exact matchup/venue cohort with 20 games;
4,850 had at least 20 prior games in the rolling-40 window. This supports the sample
selection change but does not measure accuracy or profitability.

## Reproducible research checks

Automatic observed-stat grading covers the same live core markets collected by
the scanner: NBA points, rebounds and assists; NFL passing yards, rushing yards,
receiving yards and receptions. New nflverse row commitments include receptions.
Older NFL commitments remain reproducible for yard props, while reception outcomes
stay pending unless the retained digest authenticates the reception count. The free
ESPN final-stat archive can also export receptions for unpriced walk-forward checks.

The implementation was rerun through the actual LangGraph nodes against two
previously archived ESPN final-stat datasets and the restricted PostgreSQL history.
The game date remained an exclusive cutoff, the most recent 40 prior games were
used, and no experimental context adjustment was enabled.

| Cohort | Cases | v2 Brier | v3 Brier | v2 log loss | v3 log loss |
| --- | ---: | ---: | ---: | ---: | ---: |
| NFL 2025-09-14 passing yards over 200.5 | 16 | 0.237315 | 0.236471 | 0.668644 | 0.666337 |
| NBA 2026-01-28 points over 20.5 | 192 | 0.087209 | 0.087149 | 0.434929 | 0.283616 |

The current v4 code was rerun on the same NBA archive through the actual LangGraph
and restricted hosted history. It evaluated 192 of 203 candidates with Brier
`0.087149`, log loss `0.283616`, calibration error `0.038333`, and nine distinct
game clusters; its Brier interval was `0.050317-0.123980` and log-loss interval was
`0.177962-0.389269`. The report has dataset hash
`26cbd446a4d0adc1c5a8f83bbd9e75e4ad8e375ae5141e2a32333c69c5e20b3f` and source
hash `b867111719537b78f7003059492f5e51b3058976c59dbfa6d9e8c8eb8bc51a81`.
That walk-forward contains no point-in-time matchup context, so it validates the
rolling estimator used by the fallback but not the fallback trigger itself. The
separate hosted executor replay verifies that trigger and cutoff behavior.

Reception support was checked after implementation on two retained archives with
the unchanged v3 model and a fixed 4.5 threshold:

| Cohort | Candidates | Evaluated | Brier | Log loss | Calibration error | 0% Brier | 50% Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NFL 2025-09-07 receptions over 4.5 | 205 | 122 | 0.126400 | 0.387913 | 0.097398 | 0.188525 | 0.250000 |
| NFL 2025-09-14 receptions over 4.5 | 210 | 128 | 0.139957 | 0.435221 | 0.077299 | 0.226562 | 0.250000 |

These are fixed research thresholds, not historical bookmaker lines. The NBA
cohort is highly imbalanced toward Under, multiple players share games, and both
original datasets were examined while selecting this implementation; the reception
rows were evaluated after adding their ingestion and settlement support. They are
regression evidence rather than untouched holdouts. ROI and CLV are null. Future model changes
need forward timestamped priced quotes and later untouched settlements before any
profitability claim.

### 2026 NFL Week 1 retrospective holdout

On September 15, 2026, the current v4 graph was replayed over the completed Week 1
slate as if each game had not started. Every query used the game date as an exclusive
cutoff and at most 40 prior games; the archived Week 1 ESPN box scores were introduced
only for grading. The 200.5 passing-yard and 4.5 reception thresholds were already
documented before this run. This is a retrospective time split, not a prediction file
timestamped before kickoff, and the historical database can contain later provider
corrections.

| Fixed-threshold cohort | Candidates | Evaluated | Brier | 95% game-cluster Brier | Log loss | 95% game-cluster log loss | Calibration error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Passing yards over 200.5 | 34 | 24 | 0.252302 | 0.171835–0.332768 | 0.700006 | 0.525533–0.874480 | 0.179138 |
| Receptions over 4.5 | 238 | 146 | 0.162507 | 0.119084–0.205931 | 0.490493 | 0.374478–0.606507 | 0.092394 |

The receptions cohort clears the predeclared 50% Brier and `ln(2)` log-loss
benchmarks even at the upper game-cluster interval bound. It does not clear the 5%
calibration-error check. The passing cohort clears none of those checks. Neither
cohort includes a historical sportsbook line or price, so ROI, CLV, stake, and profit
remain unavailable. The outcome archive contains 15 games and 627 player-stat rows;
its SHA-256 is `1b027a0540b5bb1be3c664a5e31a33ebd16ad5fbccfcab7e0b545b743ee086df`.
The evaluated Python source hash is
`dfd37ceb9a6a18a00b476c116477a2b3f0717f4b70669294fed6de87a1092d6d`.

The public Backtest Lab also exposes the natural directional calls behind those
scores. Across both prop types, 123 of 170 calls were correct (72.4%). A descriptive
highest-conviction view requires at least 60% probability on the model's called
side; 112 of 142 such calls were correct (78.9%). The unweighted mean accuracy
across the 15 game clusters was 78.6%, with an approximate t interval of
72.5%-84.6%. That lower game-cluster bound clears the dashboard's 65% evidence
floor with more than 100 forecasts and 10 games.

This tier was inspected after the outcomes were available. It is therefore a
descriptive cohort, not a predeclared or untouched holdout selection rule. The
thresholds are research thresholds without archived sportsbook prices, so these
rows cannot establish bet hit rate, ROI, CLV, fillability, or profit. The dashboard
keeps result filters out of the performance denominator so selecting only correct
or missed rows cannot change the reported rate.
