# Prospective NFL prop edge protocol — frozen 2026-09-23

The exploratory 2026-09-17 through 2026-09-21 priced cohort favored the sportsbook market over `empirical-jeffreys-v4`. It is not a validated selection rule. PR #185 merged at **2026-09-23 00:34:15 UTC**; forecasts captured from that instant onward form the prospective cohort. The existing selection policy is `confidence-floor-v2`.

## Measurements

Run `python -m sportsbet.quant.priced_market_audit --sport nfl --model-version empirical-jeffreys-v4 --captured-after 2026-09-23T00:34:15+00:00` with `ANALYTICS_DATABASE_URL` configured. Run it again with `--recommendations-only`. The command is read-only and checks the all-time eligible counts against `Ledger.report` before reporting the separate prospective slice.

- **All forecast probabilities:** Deduplicate the earliest eligible pregame forecast for each game, player, market, side and line. Compare model Brier with a no-vig probability from the exact same sportsbook, line and quote timestamp. Prefer a retained, source-hash-verified opposite quote when available. Score a decided integer-line outcome using model win probability conditional on no push. Report missing market pairs and a game-cluster bootstrap interval for the paired model-minus-market Brier difference.
- **Recommendations:** Use the separate accepted-only earliest-selection cohort. Report decided picks, pending picks, pushes, independent games, recorded-stake ROI and its game-cluster interval from `Ledger.report`, and same-line closing-line value where a later pregame quote exists. A one-pick win is a result, not an edge.
- **Data contract:** Keep actual pregame offer prices and quote times, source hashes, player/event identities and source-backed final stats. Exclude stale, post-start, synthetic or unverified observations under the ledger's existing rules. Published returns remain hypothetical because execution is not recorded.

## Evidence threshold

Do not describe the current model as having a measurable betting edge until **both** conditions hold in a frozen prospective model/policy cohort:

1. At least 50 independent settled games with exact paired market prices, and the 95% game-cluster interval for model-minus-market Brier lies entirely below zero.
2. At least 100 decided accepted picks across 30 independent games, with the 95% game-cluster lower bound for recorded-stake ROI above zero. Positive same-line CLV on a meaningful share of those picks is corroborating evidence; report its count and interval separately.

These sample requirements prevent alternate lines and both sides of one game from being counted as independent evidence. They are evidence targets, not a promise that the current model will qualify. New algorithms or gate changes get a new version and their own future cutoff. The exploratory 16-game slate may generate hypotheses but cannot be reused as the claimed validation set.

## Current state

At protocol start there are zero forecasts in the post-merge cohort. The all-time recommendations cohort has three distinct picks and one verified decided outcome. Future scheduled scans are enabled; the daily pipeline refreshes source-backed histories and settlements. If a scheduled run is degraded, retain the status and wait for verified coverage rather than scoring uncertain outcomes.

The scheduled `daily` NFL pipeline now writes separate all-forecast and recommendation checkpoint JSON artifacts after settlement, with a compact game-level summary in the workflow run. The canonical ledger report also accepts the same capture cutoff, so the prospective report carries verified recorded-stake ROI and closing-line value rather than mixing in earlier picks. Artifacts are retained for 90 days; the underlying append-only ledger supports later reproduction.
