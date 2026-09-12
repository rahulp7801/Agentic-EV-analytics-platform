# Prop probability model and validation

The current scanner cohort is `empirical-jeffreys-v3`. NBA and NFL prop scans use
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
