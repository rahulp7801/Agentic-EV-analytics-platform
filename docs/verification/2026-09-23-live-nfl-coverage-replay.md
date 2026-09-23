# NFL identity and history replay — 2026-09-23

## Purpose and scope

Verify that the deployed identity repair produces usable model inputs for the
retained Green Bay / Atlanta offers, without requesting new odds or publishing
expired prices. This is a present-day diagnostic, not a prospective prediction,
qualified-pick list, complete scan replay, or outcome/edge evaluation.

The retained provider response was captured at 01:43 UTC. Its cache payload hash
recomputed correctly. Free ESPN roster and nflverse identity evidence was fetched
at 20:31 UTC. The actual production quant agent queried PostgreSQL through a pool
with `default_transaction_read_only=on`, a 15-second statement timeout, and the
same 2024 season floor, September 24 exclusive date cutoff, and 40-game limit as
the scheduled model. Experimental probability adjustments were disabled.

## Observations

| Coverage check | Result |
| --- | ---: |
| Players in retained offers | 14 |
| Players matched by exact stored name alone | 13 |
| Players resolved with current verified roster identities | 14 |
| Distinct offered selections, including sides | 111 |
| Unique player/market/line model queries | 56 |
| Selections with estimates and at least 20 prior games | 74 |
| Selections below the unchanged 20-game floor | 37 |
| Unresolved selections or query failures | 0 |

The 56 production model queries completed in 1.03 seconds on this replay. This
excludes roster retrieval and the full scan's context, risk, persistence, and
publication work; it is not an end-to-end latency guarantee.

Brian Robinson Jr. resolves through ESPN `4241474` to GSIS `00-0037746`. His two
retained rushing-yard thresholds (22.5 and 23.5, four selections across sides)
each have 33 eligible prior games and a finite model estimate. Those selections
were previously omitted because history used the display label Brian Robinson.
No probability, sample floor, frozen model, or qualification rule was changed.

Source hashes, identity evidence, and aggregate results are retained in
`2026-09-23-live-nfl-coverage-replay.json`. Current roster evidence is not backdated
to the old quote capture, and the replay writes no predictions or exposure.

## Remaining collection constraints

A separate read-only budget check found daily usage 11/20 and rolling usage
310/450. The next UTC-day reset is September 24 00:00 UTC (September 23 17:00
Pacific). At those observed rolling counts, the rolling cap leaves capacity for
ordinary collection after the reset; later consumption and provider availability
must still be checked at execution.

The staged shared reserve intentionally protects one pre-lock and one final-hour
check across the scan. It is not a separate allocation per league and cannot
promise both football events a reserve-funded pre-lock refresh. The existing
ordinary quote collection, frozen board cutoff, admission gates, and caps remain.

No paid quote API request, purchase, subscription, card charge, wager, ledger
mutation, or public forecast was made by this replay. Fresh offers and subsequent
verified outcomes are still required for the prospective evaluation.
