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

## Reproducible research checks

The implementation was rerun through the actual LangGraph nodes against two
previously archived ESPN final-stat datasets and the restricted PostgreSQL history.
The game date remained an exclusive cutoff, the most recent 40 prior games were
used, and no experimental context adjustment was enabled.

| Cohort | Cases | v2 Brier | v3 Brier | v2 log loss | v3 log loss |
| --- | ---: | ---: | ---: | ---: | ---: |
| NFL 2025-09-14 passing yards over 200.5 | 16 | 0.237315 | 0.236471 | 0.668644 | 0.666337 |
| NBA 2026-01-28 points over 20.5 | 192 | 0.087209 | 0.087149 | 0.434929 | 0.283616 |

These are fixed research thresholds, not historical bookmaker lines. The NBA
cohort is highly imbalanced toward Under, multiple players share games, and both
datasets were examined while selecting this implementation. They are regression
evidence rather than fresh holdouts. ROI and CLV are null. Future model changes
need forward timestamped priced quotes and later untouched settlements before any
profitability claim.
