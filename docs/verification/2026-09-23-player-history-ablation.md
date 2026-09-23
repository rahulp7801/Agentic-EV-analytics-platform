# NFL player-history ablation — exploratory 2026-09-23

The existing v4 model uses the last 40 eligible player games before the forecast date and a Jeffreys Beta(0.5,0.5) estimate for the exact offered line. I joined the source-backed `player_stats` rows to each player's actual scheduled game, used the scanner's season/date cutoff, and recomputed all 5,296 earliest eligible recorded forecasts. Every sample size matched, and every recovered directional probability matched the stored six-decimal value within 0.000001. This validates the historical comparison inputs; it does not make the slate prospective.

The same 3,058 verified decided forecasts were scored with fixed alternative player-history weights. The paired column uses the 2,598 forecasts with a contemporaneous exact same-book opposite quote; its market no-vig Brier is **0.24514**.

| Historical estimate | All-decided Brier | Paired Brier |
| --- | ---: | ---: |
| Current Jeffreys prior strength 1 | 0.26861 | 0.26577 |
| Prior strength 5, centered at 0.5 | 0.26037 | 0.25803 |
| Prior strength 20, centered at 0.5 | 0.25289 | 0.25131 |
| Prior strength 80, centered at 0.5 | 0.24932 | 0.24861 |
| Exponential game half-life 16, Jeffreys prior | 0.26674 | 0.26442 |
| Sportsbook no-vig baseline | — | **0.24514** |

The prior-80 estimate reduces overconfidence sharply but remains 0.00347 Brier points worse than the paired market. A 10,000-resample game-cluster bootstrap over 16 games gives a descriptive model-minus-market interval of **-0.00147 to +0.00816**. The half-life-16 challenger remains 0.01928 worse than market, with interval **+0.00547 to +0.03636**. Multiple candidate strengths were inspected on this same slate; none of these numbers validates a trading edge.

I froze the prior-80 estimate as an **untraded shadow challenger**. It recovers the directional decided win count from immutable v4 probability, push probability and sample size, then uses Beta(40,40): `(wins + 40) / (decided + 80)`. This is scored in the priced audit beside the deployed model and exact market price. It does not alter picks, confidence gates or stakes. The hosted ledger still had zero post-merge forecasts when this candidate was frozen, so later games can supply an independent test. A probability improvement alone would not prove positive betting return; any future selection policy needs its own frozen prospective ROI evaluation.
