# NBA and CFB prospective exact-price protocol v1

## Registration and scope

Frozen before the cohort opens at **2026-09-25 04:00:00 UTC**. This new protocol evaluates NBA and CFB separately. It does not replace, pool with, or change the NFL protocol beginning September 23. All forecasts captured before the new cutoff, including previously accepted CFB picks, are excluded from this validation cohort even if their games have not finished. Earlier observations remain historical evidence under their original records.

Each sport uses model `empirical-jeffreys-v4` and recommendation policy `confidence-floor-v2`. No probabilities, samples, thresholds, policy decisions, stakes, or outcomes are changed. A changed or missing policy on an otherwise eligible in-scope forecast stops the report; it cannot silently mix selection policies. A future model/policy change requires a new prospective protocol. Other model versions are outside this cohort.

## Fixed evaluation

Reuse the existing source-checked priced-market audit and ledger reconciliation. Select the earliest eligible pregame game/player/market/side/line forecast within the cutoff cohort. All forecasts and accepted recommendations have separate denominators. Opposite sides and alternative thresholds are correlated observations; count independent games explicitly. Match contemporaneous sportsbook, player, event, line and quote time, require retained source commitments, and score only authenticated final outcomes. Pending, pushes and missing market pairs remain visible. Conditional no-push model probabilities are used for decided integer-line outcomes.

For each sport independently, require **50 paired decided games** and a 95% game-cluster model-minus-market Brier interval entirely below zero; also require **100 decided accepted picks across 30 games** and a 95% game-cluster recorded-stake ROI interval entirely above zero. Report same-line CLV coverage and interval as corroboration. Use the existing 10,000 bootstrap draws and fixed seeds. Do not pool sports, select favorable markets after viewing outcomes, or reinterpret an untraded shadow's probability score as a strategy return. A supported result remains hypothetical recorded-price evidence, not executed profit. A claim spanning both sports requires both separate evaluations to pass.

The report includes original per-sport all-forecast and recommendation aggregates, the unchanged evidence gate assessment, protocol identity, observation time and evaluator source digests. Source/identity/cutoff validation or ledger-count disagreement fails closed. A run before the cohort opens is explicitly `awaiting_start`; no pre-cutoff records become prospective. This runner does not fit a model, search parameters, or promote one.

## Operation and limits

Implement an opt-in, read-only CLI against one repeatable-read hosted database snapshot. Outputs are local aggregate JSON only, containing no forecast IDs or raw player records. Do not enable new scheduled publication or attach result artifacts without the pending publication approval. The existing NFL workflow, frozen shadow evaluators and source checks remain unchanged. No fetching of prices, paid API requests, purchases, bets, reserve changes or quota changes are needed.

The first cohort checkpoint is the first ordinarily scheduled eligible scan after the cutoff; do not trigger a quote collection to populate it. Audit source coverage and pending outcomes after the next normal history/settlement update. NBA may remain empty until in-season offers and sufficient pregame source evidence exist. Zero valid observations means insufficient evidence, not a performance result.
