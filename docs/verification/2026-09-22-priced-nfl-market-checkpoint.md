# Priced NFL forecast checkpoint — 2026-09-22

## Scope

Read-only audit of the hosted `analytics.predictions` ledger as observed on 2026-09-22. The recorded algorithm is a Jeffreys beta-binomial estimate from a player's historical outcomes at the exact offered line, with a minimum sample, a Wilson lower-bound price gate, and fractional Kelly sizing. This checkpoint uses the ledger's pregame/provenance eligibility and earliest eligible prediction per game, player, prop, side, and line. It is an evaluation of recorded forecasts, not executed wagers.

Of 12,132 stored NFL forecasts, 708 failed quote-provenance eligibility. The remaining 11,424 reduce to 5,296 earliest selections, of which 3,058 have verified decided outcomes and 2,238 remain pending. These counts reproduce `Ledger.report(sport="nfl")`: 6,128 duplicates, Brier 0.2686136, hypothetical unit-stake ROI -5.986%, 16 settled game clusters. All settled rows passed the ledger's source-evidence verification at this checkpoint.

## Market comparison

For each earliest selection, an opposite-side offer was matched only when game, player, prop, line, sportsbook, and exact quote timestamp agreed. The no-vig probability is `raw_side / (raw_side + raw_opposite)`, where raw probabilities come from the recorded American prices. This yields 2,598 decided pairs across 16 games. Missing opposite-side offers are omitted from this paired comparison.

| Cohort | Decided | Model Brier | Market Brier | Hypothetical flat-stake ROI |
| --- | ---: | ---: | ---: | ---: |
| All earliest eligible selections | 3,058 | 0.26861 | 0.24719 (raw implied, includes vig) | -5.99% |
| Exact opposite-side quote matched | 2,598 | 0.26577 | 0.24514 (no vig) | — |

The paired model-minus-market Brier difference is **+0.02063**; lower is better. A deterministic 10,000-resample bootstrap over the 16 game clusters gives a descriptive 95% interval of **+0.00508 to +0.03845**. Alternate lines and both sides within a game are correlated; this interval is not evidence of an independent 2,598-bet sample. The model underperforms the contemporaneous market in this short historical cohort.

On the full earliest cohort, Over forecasts returned -15.50% at recorded prices, Under forecasts +3.48%; this side split is exploratory and confounded by the same 16 games and many correlated lines. It is not a trading rule. The public recommendations cohort has only three distinct picks, one verified decision and two pending at this checkpoint, so its +140% recorded-stake ROI on one settled pick cannot establish an edge.

## Next decision rule

Treat the sportsbook's contemporaneous no-vig probability as the benchmark for probability scoring. Any model change should be frozen before a later game slate and evaluated on exact pregame quotes, verified settlements, and deduplicated picks. Report paired Brier improvement, recorded-price return, closing-line value, number of games, and uncertainty by game. Do not promote a profitable-looking filter selected from these 16 games as a validated edge.

The immediate research priority is to check whether anchoring player-history estimates to the market improves calibration on later games. A better Brier score alone would improve forecasting but would not prove positive expected betting return after vig; that requires a separately frozen selection rule and prospective priced outcomes.

## Reproduce

Run `python -m sportsbet.quant.priced_market_audit --sport nfl` with the ledger connection configured through `ANALYTICS_DATABASE_URL`, or set `--database-env` to the name of an existing environment variable containing that URL. The command is read-only. It checks its earliest-selection, decided, and duplicate counts against `Ledger.report` and stops if they differ. Its exact quote pairs are constructed from eligible recorded forecasts; the report above was independently checked against the hosted ledger.

Future scans now record `market_no_vig_probability` when the chosen side has exactly one opposite offer from the same sportsbook, line, quote timestamp, game and provider batch. They also retain the opposite American price and its source-record hash. Missing or ambiguous opposite quotes leave these optional fields absent. This is a contemporaneous benchmark and does not change the model estimate, recommendation gate, or stake.
