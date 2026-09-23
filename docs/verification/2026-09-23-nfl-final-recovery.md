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
