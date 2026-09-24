# Reserve timing and public workflow recovery — September 24, 2026

## Verified public recovery

Scheduled public workflow [36054990798](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/36054990798), created 20:27:30 UTC on release `af0b9df`, passed. Its original captures converged after twelve bounded waits. All required public endpoints, including NFL game logs, passed. This closes PR #225's next-scheduled-run checkpoint. The previous isolated game-log HTTP 503 has not recurred in this run; its original cause remains unconfirmed.

## Consumer reporting gap and fix

The 18:38 UTC scan deferred one NFL and 22 CFB events for the staged pregame reserve. Event states explained the reason but omitted when that reserve would next ease. The scanner now records `next_reserve_release_at` only when the exact reservation reason is `pregame_credit_reserve`. It derives the next transition from the existing holdback policy (two hours or one hour before kickoff), without reserving credits or requesting data.

Upcoming game cards show a separately labeled **Next reserve window** only for a fresh, unique exact team/kickoff match with a valid future timestamp before kickoff. Stale, duplicate, mismatched, missing, expired, or started-game evidence does not show a future window. Daily and rolling budget failures do not borrow this label. The text explicitly leaves collection dependent on worker timing and available credits. It does not promise a quote or a qualified pick.

Local verification: 108 scanner/budget tests and 12 slate tests passed. Tests cover both reserve transitions, no release when the reserve is absent/exhausted, unchanged reservation behavior and request counts, and public projection rejection cases. Desktop/mobile QA and CI results are recorded in the pull request.

## Prospective evidence checkpoint at 21:15 UTC

The latest scan remains `51f9a11206eb402ca2ed5c70464cf755`, completed 18:38:29 UTC. The prospective cohort has 241 raw NFL forecasts, zero accepted records, and zero authenticated settlements. Frozen role evaluation remains ten pending paired thresholds, zero decided games, and no promotion evidence. Daily usage is 12/20, rolling usage 322/450.

The first CFB reserve stage opens 21:30 UTC (Liberty–Coastal Carolina kickoff 23:30 UTC); NFL opens 22:15 UTC (Atlanta–Green Bay kickoff September 25 00:15 UTC). GitHub schedules are best effort; inspect the next normal worker after each stage, and the regular free NFL history refresh at 22:29 UTC. Verify newly recorded reserve fields in a fresh scan/slate response. No extra quote collection, purchases, or bets were triggered for this work. All frozen artifacts, qualification gates, reserve decisions, and credit caps remain unchanged; PR #194 remains excluded.
