# Hosted evidence audit source and transaction checks — 2026-09-23

## Observed gaps

The priced-audit CLI constructed `Ledger()` when its configured environment
variable was missing. That could initialize `.checkpoints/analytics.sqlite` and
report an empty local cohort instead of reading production. It also used ordinary
read/write-capable connections despite its documented read-only contract, and
its report/forecast/closing-quote reads could observe different database states.

The recovery follow-up initially queried the default schema for API usage. The
ledger actually uses `analytics` in the existing database. The corrected read-only
check confirmed 11 credits used on September 23. The prior report's inaccurate
unavailable-database explanation has been corrected explicitly.

## Changes

- Default hosted source: `ANALYTICS_DATABASE_URL`, then `DATABASE_URL`. An explicit
  `--database-env NAME` requires that exact variable; an absent or malformed source
  fails without opening or creating a local ledger. URLs are never printed.
- Share the read-only PostgreSQL ledger adapter between priced and workload-shadow
  audit commands. Read-only mode is enforced by PostgreSQL, with bounded statement
  and idle-transaction timeouts and the proper `analytics, public` search path.
- Keep each priced audit in one repeatable-read snapshot, including the canonical
  ledger comparison and closing prices. Connection/counter errors fail the command
  with a safe error type rather than outputting a partial report or credentials.
- Leave eligibility, grouping, uncertainty, frozen coefficients, prospective
  cutoffs, source commitments, and qualification policy unchanged.

## Live collection checkpoint

The scheduled collector had not run since 18:08 UTC. The existing all-sport scan
was dispatched without changing caps or reserve rules. Run
[35911713276](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/35911713276)
finished successfully and published scan `21a6c31de0124a37817b5f36182f20a1` around
19:48 UTC. NBA had no eligible events. NFL and CFB each deferred one event because
of `pregame_credit_reserve`; there was no new quote or forecast capture. Database
usage remained 11/20 daily credits. The rolling cap remains 450. These are honest
coverage limitations, not model rejection or evidence of an edge.

The full sanitized scan checkpoint is retained in
`2026-09-23-live-collection-checkpoint.json`. The latest direct ledger inspection
found zero forecasts captured after the workload-shadow freeze. No evaluation
result is promoted and no stale quote is republished as a current pick.

## Verification

57 local audit, frozen-shadow, and evidence-gate tests passed. The PostgreSQL
regression checks a concurrent writer is invisible inside the audit snapshot,
visible after it ends, and a direct write through the audit adapter is rejected
by PostgreSQL. Full CI gates release. This change makes no paid provider requests
and authorizes no new quota, purchase, subscription, card use, or wager.
