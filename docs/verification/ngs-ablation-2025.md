# NFL Next Gen Stats ablation: 2025 holdout

## Decision

Retain Next Gen Stats as explanatory evidence only. No tested feature group met
the promotion contract, and `EXPERIMENTAL_PROBABILITY_ADJUSTMENTS` remains false.

The model was fitted on 2024 examples and evaluated once on the untouched 2025
regular-season outcomes. Each example used 20-40 earlier player games, at most
eight earlier NGS weeks, an exclusive target-week cutoff, and a rolling half-point
median research threshold. Lower scores are better. Every interval below is a
paired 95% percentile interval from 2,000 deterministic whole-game-cluster
resamples; the delta is candidate minus production baseline.

| Prop | Train / holdout | Games | Complete NGS coverage | Brier baseline to candidate (delta interval) | Log loss baseline to candidate (delta interval) | Calibration error baseline to candidate (delta interval) | Decision |
| --- | ---: | ---: | ---: | --- | --- | --- | --- |
| Passing yards | 220 / 393 | 251 | 3.45% | 0.2495 to 0.2604 (+0.0035 to +0.0183) | 0.6922 to 0.7143 (+0.0072 to +0.0374) | 0.0331 to 0.1002 (+0.0099 to +0.1209) | Reject |
| Rushing yards | 552 / 825 | 271 | 7.24% | 0.2494 to 0.2674 (+0.0098 to +0.0262) | 0.6920 to 0.7360 (+0.0247 to +0.0650) | 0.0310 to 0.0982 (+0.0354 to +0.0968) | Reject |
| Receiving yards | 1,324 / 2,099 | 272 | 18.41% | 0.2494 to 0.2527 (+0.0014 to +0.0054) | 0.6920 to 0.6987 (+0.0028 to +0.0109) | 0.0362 to 0.0628 (+0.0232 to +0.0329) | Reject |
| Receptions | 1,324 / 2,099 | 272 | 18.41% | 0.2332 to 0.2359 (-0.0002 to +0.0057) | 0.6591 to 0.6646 (-0.0008 to +0.0116) | 0.0314 to 0.0504 (+0.0018 to +0.0303) | Reject |

Coverage is the share of all provenance-valid, history-eligible player weeks that
also had a complete prior NGS feature vector. This deliberately broad denominator
does not reconstruct which players a sportsbook offered. The thresholds are not
historical sportsbook lines, so this result does not establish a win rate, ROI,
CLV, profit, or betting edge.

The run read 54,422 weekly player rows, 7,350 NGS rows, and 856 schedule rows.
The full ignored local report SHA-256 is
`1a94084f24e0fa750f4901e6193a49a6ab22f6bbef9e37bc5b83b841703c5fc3`.
The evaluated Python source digest is
`059d2658dc54bf34d705aeb33e5264f933edfed830f4c608a4ead41a72085535`.
Two consecutive runs against unchanged source commitments produced the exact same
report SHA-256.

Reproduce the report with:

```powershell
uv run python -m sportsbet.quant.ngs_ablation --train-season 2024 `
  --evaluation-season 2025 --output .local/ngs-ablation-2025.json
```
