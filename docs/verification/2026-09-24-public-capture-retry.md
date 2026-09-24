# Public capture readiness and strict snap refresh — 2026-09-24

## Observed failure

Public market data workflows [36037261843](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/36037261843) and [36037939015](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/36037939015) collected successfully but failed deployed readiness at 18:04:44 and 18:09:57 UTC. The mismatches were NFL schedules and NFL markets respectively. Both ran release `9bfadb6aaefe8bb98ec4775e32c8c3ecb7f29a6e`.

At 19:19:16 UTC all four ordinary NBA/NFL market/schedule endpoints returned HTTP 200 and exactly matched the latest failed run's original collection timestamps. Database snapshots matched too. Replaying that original report through production verification exited 0 without another collection. The evidence supports cache propagation delay; the original failure logs did not retain the actual mismatched timestamp, so the exact stale cache layer cannot be established retrospectively.

The public CDN permits 30-second caching plus 30-second stale refresh, while the server snapshot cache revalidates after 60 seconds. First reads can therefore return stale values while refreshing. Query cache-busters are rejected with HTTP 400 by the strict API query contract; that contract remains unchanged.

## Fix and verification

The public workflow permits at most 37 capture checks, separated by at most 36 five-second waits. Only endpoints with mismatched captures are retried. HTTP time is additional and individually bounded by the existing request timeout. Security, CSS, and healthy endpoint checks are not repeated. The exact capture timestamp must match the original run: older, newer, or missing timestamps still fail. Non-200 retry responses fail immediately. Default verification remains one attempt unless explicitly configured.

Twelve focused readiness tests passed, including transient convergence, healthy endpoint isolation, persistent older/newer/missing capture rejection, and retry bound validation. Production replay using the original report passed. CI and release status will be recorded on the linked pull request. No quote collection was triggered to test this fix.

## Strict snap ingestion production proof

PR #224's strict importer executed in successful daily workflow [36037187315](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/36037187315), logging 2,994 rows at 17:51:57 UTC. The later public workflow 36037939015 refreshed those rows again; latest database source observation is 18:05:37.259388 UTC. Its subsequent readiness failure did not roll back the successful refresh.

A read-only recomputation verified every current 2026 row commitment and the ordered batch hash against the retained source archive: `b9878983090c28206edf613eb5e67b20dd18dd652f74b3da128b518f2a17fb5a`. All 2,994 rows match. This closes the pending first-production-refresh checkpoint for PR #224. Compact evidence is retained in `2026-09-24-public-capture-retry-evidence.json`.

## Prospective checkpoint

Scan `51f9a11206eb402ca2ed5c70464cf755` finished 18:38:29 UTC: one eligible NFL event and 22 CFB events were deferred by the existing pregame reserve; NBA had none. No quote attempts or scan failures. Usage remains 12/20 daily and 322/450 rolling credits. There are no accepted picks or authenticated settlements in the tracked prospective cohort. The frozen role shadow still has ten pending paired thresholds (seven receiving-yards, three receptions), zero decided paired games, and no promotion evidence.

Next scheduled evidence windows: first CFB reserve stage at **21:30 UTC September 24** (Liberty–Coastal Carolina kickoff 23:30 UTC), NFL reserve stage at **22:15 UTC** (Atlanta–Green Bay kickoff September 25 00:15 UTC), and ordinary free NFL refresh at **22:29 UTC**. Inspect the next naturally scheduled public workflow for exact capture verification after caches converge. Preserve PR #194's unapproved status, all reserve/credit limits, frozen versions, and qualification thresholds. No spending, purchases, bets, or extra odds collection were performed.
