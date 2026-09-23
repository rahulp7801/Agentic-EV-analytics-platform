# Explicit NFL final-result recovery

## Why these rows were missing

The September 23 backlog audit found 213 unresolved September 20/21 NFL forecasts with valid final-game identities but no nflverse player-stat row. ESPN's summary receiving box score also omits players with no receiving activity. Its event-specific athlete statistics endpoint explicitly records receptions, receiving yards, and games played for eight of these players.

The source bundle establishes **eight played games with explicit zero receptions and zero receiving yards**, covering **201 raw forecasts**. The other two players, Puka Nacua and Jauan Jennings, are explicitly marked did-not-play on their event rosters; their **12 forecasts remain pending**. No sportsbook void rule is inferred.

The preview contains 100 true and 101 false outcomes. These include repeated quotes and opposing sides; none were accepted recommendations. They are not independent samples, evidence of profitable picks, or new prospective observations. All captures predate the frozen September 23 evaluation cutoff.

## Source checks

The recovery validates:

- Exact completed ESPN regular-season event, kickoff, Eastern calendar date, both teams, season and week.
- Hash-committed nflverse GSIS/ESPN/PFR crosswalk with unique bindings; names never join players.
- Exactly one occurrence of the athlete across both event rosters, `didNotPlay=false`, valid full-game roster entry, and all event/athlete/stat reference paths.
- Explicit full-game `gamesPlayed=1`, receptions and receiving yards. Missing fields, duplicate categories, invalid numeric types and inconsistent totals fail closed.
- Independent nflverse offensive snap counts greater than zero for the same PFR ID, game, week, team and opponent. Retained row hashes and observation times are verified.
- Postgame source observation times and commitments to every archived response.
- Exact original forecast kickoff/teams/player, valid pregame capture, and the existing verified-settlement proof contract.

Raw public ESPN responses, the published nflverse identity crosswalk, and the eight retained participation records are archived in `2026-09-23-nfl-final-sources.json.gz`. The sources contain no credentials. The archive is intentionally retained so missing zero rows can be independently reproduced without another collection request. The archive hash and per-player results appear in `2026-09-23-nfl-final-preview.json`.

## Apply boundary

`python -m sportsbet.quant.nfl_final_recovery --bundle docs/verification/2026-09-23-nfl-final-sources.json.gz --expected-count 201` defaults to a read-only hosted preview. The database URL follows the explicit read-only audit configuration; it never silently opens a local ledger.

After review, `--apply --expected-count 201` runs one bounded transaction. It locks every target row and rejects changed payloads, already populated outcomes, conflicting source stats, invalid proofs, or a changed result count before updating result columns. Errors roll back the transaction. Original forecast payloads, prices, stakes, history rows, frozen model/evaluation artifacts, and provider budgets are not written. A later ordinary history refresh can still correct results using newly observed authenticated stats.

This is an explicit archive-driven recovery command, not a new scheduled collector. Future use requires another reviewed source bundle. The command performs no network collection, purchases, bets, or quote requests.

## Tests and next checkpoint

The initial parser/settlement suite passed 76 tests. The independent participation expansion passed 44 focused tests. PostgreSQL CI exercises atomic writes, payload/result races, conflicting final stats, retained forecast equality, verified reports and repeat-run exclusion.

After applying, verify all 201 stored proofs independently, confirm the 12 DNP and 708 invalid-identity forecasts remain unresolved, compare immutable forecast/history hashes, and refresh dashboard metrics from the verified ledger without an odds scan. Continue the scheduled prospective collection after the daily quota reset. No edge claim is warranted by this historical repair.


## Production result: verified at 22:21 UTC

PR #210 merged as `692b92cced31370a0aeceaf352164f55275dc6cc`. Its full production CI, schema verification, deployment and readiness check passed. CI included 1,062 backend tests, 9 migration tests and 30 PostgreSQL integration tests.

The reviewed recovery committed exactly 201 results in one transaction at 22:20 UTC. All 201 stored proofs independently reproduced from the archived source bundle. The fingerprint of 11,328 retained forecast payloads and the core stat commitments of all 56,645 NFL history rows stayed unchanged. The remaining historical pending rows are exactly 708 invalid-identity forecasts, 4 Jauan Jennings DNP forecasts and 8 Puka Nacua DNP forecasts.

Overall and NFL dashboard metrics were republished directly from the verified ledger, without an odds scan. Public `/api/metrics?sport=nfl` returned HTTP 200 with 5,403 eligible earliest selections, 5,284 settled, 119 pending, 708 metadata exclusions and zero unverified settlements. The increase from 5,208 to 5,284 settled selections is 76 after deduplication, not 201 independent observations. Accepted recommendation outcomes are unchanged.

The applied receipt, independent checks and public counters are retained in `2026-09-23-nfl-final-result.json`.

### Next independent model-quality task

Quantify missing historical player-stat rows among exact-ID offensive participants. This recovery demonstrates eight played games whose explicit receiving zeroes were absent from the production history table. Such omission can bias a rolling distribution toward games with recorded activity. Audit the frequency and impact using source-backed game participation and explicit final totals; do not infer zeroes from missing rows or rewrite frozen prospective inputs. Any estimator or history-policy change needs a separately versioned prospective shadow and the existing evidence gates.

The next scheduled market evidence checkpoint remains September 24 00:00 UTC (September 23 5 PM Pacific), followed by the existing CFB/NFL pregame collection windows. No paid quota was consumed by the recovery.
