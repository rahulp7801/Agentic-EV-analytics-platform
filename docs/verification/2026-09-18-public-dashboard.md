# Public dashboard verification, 2026-09-18

The deployed interface, payout calculations and tested access controls passed
verification. A profitable betting edge and a win rate above 60% on accepted
pregame picks **have not been established**. Provider access, credential
rotation and verified edge rate limiting remain release limitations.

## Deployed software checks

[PR150](https://github.com/rahulp7801/Agentic-EV-analytics-platform/pull/150)
and [PR151](https://github.com/rahulp7801/Agentic-EV-analytics-platform/pull/151)
merged through protected master. The verified application source is
`c585d402447befe18e01c8c83debd4873105e708`.
[Protected-master CI and deployment](https://github.com/rahulp7801/Agentic-EV-analytics-platform/actions/runs/35390041595)
and [master security analysis](https://github.com/rahulp7801/Agentic-EV-analytics-platform/actions/runs/35390041238)
passed. Exact-head PR checks passed before merge:

- 708 backend tests passed; 28 environment-dependent tests skipped. The separate
  PostgreSQL job passed eight migration and 17 integration checks.
- 121 frontend regressions, lint, TypeScript and production build passed.
- Worker isolation, secret scanning, dependency audits, Bandit, all three CodeQL
  analyses and aggregate CodeQL passed.
- Actual production landing-to-desk entry, player photos/identity, navigation and
  all 730 research forecasts/50 players passed at desktop 1440 and phone 390.
  Settled-state accessibility checks reported zero tested WCAG violations;
  horizontal overflow checks passed.
- Local-only qualified fixtures verified exact sportsbook/side/line/price,
  independent win/loss/refund arithmetic, copying and copy-time quote expiry.
  A 65% win probability at +100 with no push gives expected net +$30 per $100;
  this fixture is never published as an observed production bet.
- Production bounded HTTP checks rejected unexpected/duplicate/oversized inputs,
  cross-site browser reads, mutations and forged prefetch input. Private files
  returned 404; SQL-shaped search stayed literal; fresh HTML nonce CSP/security
  headers passed. Public image optimization is disabled.
- Early scroll plus three return-to-top cycles preserved the production hero
  on both widths.

The shortlist contains at most three independently qualified selections. Every
price must be fresh and every worker/model/roster/risk check must pass. Research
pagination cannot supply a partially inspected strongest-pick shortlist. The
current production shortlist is empty.

## Recorded-prediction evaluation

The existing Linux
[public daily workflow](https://github.com/rahulp7801/Agentic-EV-analytics-platform/actions/runs/35390570678)
ran the source-backed NBA/NFL history, schedule, settlement and metric pipeline.
Both history refreshes and settlement steps completed. The overall workflow
returned exit 2/degraded coverage because NFL Kalshi discovery was partial
(three of four prop series) and PrizePicks returned access denied. This is a
provider-coverage failure; it does not mean that deployment tests failed.
Sportsbook prices and new prop recommendations were intentionally outside this
public-only operation. No orders were submitted.

Evaluation captured after that run:

| Cohort | Evaluated selections | Decided | Pending | Historical win rate | 95% nominal Wilson interval | Decided games |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| NFL accepted pregame recommendations | 0 | 0 | 0 | Unavailable | Unavailable | 0 |
| NFL all eligible priced forecasts, unit stakes | 850 | 360 | 490 | 50.0% (180/360) | 44.9–55.1% | 1 |
| NBA accepted pregame recommendations | 0 | 0 | 0 | Unavailable | Unavailable | 0 |
| NBA all eligible priced forecasts, unit stakes | 0 | 0 | 0 | Unavailable | Unavailable | 0 |

The immutable ledger inventory contains 2,002 `empirical-jeffreys-v4` forecast
records and **zero `accepted=true` records**. It retains 804 raw verified
settlements and 1,198 raw pending records. Raw rescans are distinct from the
earliest eligible selection cohort: the NFL report excludes 708 records lacking
original home/away identity and removes 444 repeated selections, leaving 850.
The new scanner requires exact settlement identity; missing historical identity
is not filled retrospectively.

The all-forecast cohort includes rejected selections and paired Over/Under
forecasts. Its 50% aggregate rate is not the accuracy of a directional best-pick
strategy. Its 360 decided selections come from one game; the nominal Wilson
interval assumes independence that these selections do not satisfy. A
game-cluster interval cannot be calculated with one game. Repeated players
across games would remain an additional limitation even with more games.

On the same decided forecast cohort, Brier score is `0.27305157942835556`, worse
than the fixed 50% baseline `0.25`; log loss is `0.7476852754951715`. Unit-stake
replay ROI is `-5.0687306178840014%`. This is hypothetical quote replay, not
executed account profit. None of these figures establishes profitable accepted
picks or a win rate above 60%.

Current raw rejection counts are 961 no-positive-edge, 609 edge-not-confident,
349 insufficient-sample and 83 edge-review-limit records. Removing those
checks after seeing results would create a different hypothetical strategy.
Retrospective landing demonstrations retain their separate research scope.

## Evidence and reproduction

Capture time for the final read-only ledger inventory:
`2026-09-18T20:27:07.375736+00:00`. The restricted worker transaction enforced
read-only SQL and verified certificate/hostname TLS.

- Final ledger capture SHA256:
  `1ef60979f49cc7bc6abd96b7af663974a0508a139a3abdc8f19aea88689de49e`.
- Published metric capture SHA256:
  `a7cd2ac1f93c6efce05ea0f56276e17eaa85024fc87dcc8c9de79db3ffd949b5`.
- Raw captures, audit scripts, scanner reports and browser evidence remain in
  ignored `.local/`; no credentials or private diagnostics are public artifacts.

The evaluation routes are `/api/metrics?sport=nfl&cohort=recommendations` and
`/api/metrics?sport=nfl&cohort=all`, with corresponding NBA routes. These live
routes change as evidence arrives; use the dated capture for this verdict.
The existing worker publishes `Ledger.report(recommendations_only=True)` for
accepted picks and retains prediction/quote/stat evidence commitments.

The existing refresh/evaluation operation can be repeated without paid odds
collection:

```powershell
gh workflow run public-data.yml --repo rahulp7801/Agentic-EV-analytics-platform --ref master -f operation=public_daily -f sport=both
```

Success criteria for a future above-60% claim require an explicit pregame
selection policy, actual archived prices and accepted flags, verified outcomes,
all losses/pushes/voids/pending records, an untouched chronological holdout and
adequate independent-game coverage. Report measured rate and uncertainty;
do not tune filters on the same results until a desired percentage appears.

## Security limitations

The Supabase browser-role view access gap is closed in the live database.
Restricted application roles and verified TLS remain usable. Full audit details
and residual risks are in [SECURITY.md](../../SECURITY.md).

The historically exposed Odds credential remains active; provider rotation is
required even for a free key. Effective Vercel edge rate limiting is unverified:
stored configuration did not produce a 429 in the bounded check, and in-place
correction returned a plan-related 403. Automatic approval review rejected
clearing the existing rule before recreation because recreation could fail;
no clear/recreate was applied. Preserve existing protections while resolving
account-side activation. There is no DDoS-immunity claim, production flood
test, verified spending-limit setup or external penetration-test certification.

The latest credentialed collector separately reported its configured odds
budget exhausted, and PrizePicks access denied. Those external constraints
cannot be solved by exposing stale prices as current picks.
