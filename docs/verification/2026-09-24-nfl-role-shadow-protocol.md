# NFL role-history shadow v1: frozen prospective protocol

## Purpose and scope

The prior history audit found twelve explicitly observed receiving zeroes missing from four players' database histories. This candidate tests a fixed rule that both includes those observations and distinguishes the current season/team from older observations. It does not isolate the causal contribution of each change. It has no fitted coefficients, calibrated uncertainty interval, acceptance policy, stake allocation, or automatic promotion.

Version: `nfl-role-history-shadow-v1`. Policy: `explicit-receiving-role-prior20-v1`. Formula and source freeze: **2026-09-24 00:42:34.845799 UTC**. Deployment and actual ledger receipts must also precede every evaluated game's start; the freeze alone does not make retrospective replay prospective. The implementation/source/artifact commitments are in `2026-09-24-nfl-role-shadow-loader.json` and each valid ledger record.

Scope is Austin Hooper, Jahan Dotson, Christian Watson and Chris Brooks; NFL receptions and receiving yards, nonnegative half-integer lines only. The packaged source archive contains the same twelve final observations verified in PR #214 plus the exact published identity crosswalk. Results are not generalized to other players, NBA, CFB, passing or rushing markets. Expansion or changes to this model require a new version.

## Fixed probability rule

Use the most recent 40 verified games before the target game date within the current and previous two seasons, with a minimum of 20. The explicit receiving overlay is applied before window selection. A later provider row agreeing with the recovery is counted once; a conflicting row makes the candidate unavailable.

Partition that window into current-season games for the freshly observed current roster team, and all remaining games. These groups are disjoint. Require at least one current-role game. For an over line:

```
older_probability = (older_over_hits + 0.5) / (older_games + 1)
candidate_probability = (current_over_hits + 20 * older_probability) / (current_games + 20)
under_probability = 1 - candidate_probability
```

The fixed prior strength 20 is a research design choice, not a tuned or validated optimum. Current team/season is a coarse role proxy; targets, routes, snaps, injuries, opponents and teammate changes do not adjust this probability. At the initial checkpoint there are only two current-role games per player. Old-season transportability remains an assumption being tested.

## Evidence and chronology contract

- Capture database inputs once in a read-only repeatable-read transaction, bounded to the four identities and 301 rows per source; reject overflow. The optional loader has a five-second timeout and failures become explicit unavailable attempts.
- Validate published GSIS/PFR/ESPN identity, exact game/week/team/opponent, stat and participation hashes, and source observation timestamps. Every observed positive-offensive-participation gap must have an explicit matching recovered result. Every model stat game must have a matching participation record. Missing outcomes remain unknown.
- This is coverage of **observed participation records**, not a complete independent census of every game the athlete played. A fresh database read does not prove that a delayed upstream participation feed is complete. Report this limitation; do not call the history league-wide complete.
- Require the current roster observation to be no more than one hour old with the pinned ESPN player ID, exact ESPN roster endpoint and source commitment. Availability changes screen the production pick separately and do not become numerical adjustments in this candidate.
- Require the exact current baseline history count, probability and rounded mean to match the recorded production estimate. A concurrent history revision causing disagreement makes the candidate unavailable.
- Require the quote and history snapshot to precede capture by at most five minutes, the exact quote commitment, matching settlement identity, post-freeze capture, and a server-owned immutable ledger receipt within five minutes of the quote and before kickoff. An invalid/late candidate is downgraded; the original production record is preserved. Retries retain the original receipt and evidence.
- Replay the retained candidate inputs and verify source, artifact, implementation, offer, availability and record commitments before scoring. No old prediction or previous shadow artifact is rewritten.

## Prospective evaluation

The audit retains all eligible candidate attempts, including unavailable attempts. Select the earliest attempt per game/player/market/line before inspecting availability, price pairing or outcome; complementary sides, books and rescans cannot inflate the sample. Pending and unpaired attempts remain visible.

Use only authenticated decided settlements and matching captured two-sided, no-vig market baselines. Compare Brier score and log loss against both production and market probabilities. Weight games equally, then players within games, then lines within player-games. Report separate game- and player-clustered 95% intervals.

For each market, at least **50 distinct paired games** and negative upper 95% bounds for both metrics, both comparators and both clusterings are required to label predictive evidence supported. Four players on two teams make this a slow, narrow experiment; player-cluster uncertainty is particularly limited. The report always returns `promote=false`. Separate cluster intervals do not fully model cross-cluster dependence. There is no ROI, staking, validated edge or launch-readiness claim from these scores alone.

Internal snapshots use `role-shadow-validation:{sport}`; the existing frozen workload-shadow snapshot remains separate. Capture is enabled by `ROLE_HISTORY_SHADOW_ENABLED` (default true); disabling it stops this optional input read and candidate capture. Public forecasts, pick qualification, exposure and quote collection policy are unchanged.

## Verification before deployment

Read-only execution against the hosted database successfully loaded and validated all four histories. Formula diagnostics: Hooper over 0.5 receptions 83.42% (35 games); Dotson over 1.5 24.03% (36); Watson over 4.5 13.29% (27); Brooks over 0.5 52.93% (32). Each has two current-role games. These are mathematical checks using existing data, **not prospective forecasts, offered prices or qualified picks**. Brooks's example is a chosen diagnostic threshold, not a claim that a retained book offered it. No diagnostic row was written to the prediction ledger.

Tests cover explicit overlay and no double counting, conflicts, missing participation/stats, source/cutoff/roster/baseline mismatch, replay tampering, monotonicity, immutable/late receipts, old-shadow coexistence, earliest-unavailable attempt retention, and scanner equivalence with the feature enabled/disabled or input loading failed. CI additionally exercises disposable PostgreSQL and the isolated worker image with the pinned source artifact.

## Next evidence checkpoint

After deployment, inspect the next **normal scheduled** NFL collection. Distinguish a scheduler success from an actual fresh quote capture. Record per-event attempts, inference reasons, server receipts and the first valid paired candidate count; retain unavailable denominators. After that game's authenticated final settlement, rerun the read-only role audit alongside the existing frozen-shadow and priced-market reports. Never backfill this candidate onto pre-freeze or already played offers.

Keep the staged pregame reserve and limits at 20 daily / 450 rolling. Do not dispatch redundant quote collection or merge PR #194. This change makes no odds API calls and buys nothing; it adds bounded reads and internal evidence to the already scheduled evaluation path.
