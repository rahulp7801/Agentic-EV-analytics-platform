# NBA source-provenance recovery — 2026-09-23

## Evidence and repair plan

The initial read-only audit found 52,957 NBA rows across seasons 2024 and 2025
with provider `nba` but no source-record commitments. Free official PlayerGameLogs
responses were successfully retrieved from this machine for both seasons.

Every stable player/game ID, date, team/opponent, home/away flag, playing-time
value (at the database precision), and counting stat matched the official data.
There were 198 name-label differences in 2024 across five stable IDs: accents in
Jonas Valanciunas, Lester Quinones, and Vlatko Cancar; and Jr. suffixes for Bobby
Portis and Brandon Boston. Their IDs and every model value matched.

An initial planner classified the 2025 rows as having existing provenance because
they carried an observation timestamp. Independent verification found that all
26,651 had a September 11 timestamp but neither source hash. That is not verified
provenance. The corrected planner can recover timestamp-only rows, preserves any
existing hashes, and refuses to replace a later observation with older evidence.
The exact corrected plan and source hashes are in
`2026-09-23-nba-provenance-plan.json`. All 52,957 rows remain in recovery scope,
including the 198 official name labels.
The source observation times are September 23, 2026; nothing is backdated to the
historical games or original research period.

## Recovery implementation

`sportsbet.ingestion.nba_provenance` downloads the free official season endpoint.
Its default mode is a read-only audit; `--apply` explicitly enables recovery.

- Validate official regular-season/base/totals scope, requested season, bounded
  response size, unique player/game identities, dates, matchup, and valid stats.
- Compare every stored model value to the normalized official response. Playing
  time uses PostgreSQL's existing one-decimal storage precision.
- Update only rows from `nba` with both source hashes missing. Existing or partial
  hashes, later observations, other providers, missing source rows, and changed
  model values are excluded and counted. A legacy timestamp without hashes is
  replaced with the actual observation time of the matching official response.
- Retain an exact source-response archive and its SHA-256 before writes. Store
  the same normalized batch and core-stat row commitments used by normal NBA
  ingestion, plus the actual present-day observation time.
- Update the official player display name only through an exact stable ID and
  all-model-value match. No name similarity is used to join records.
- Compare all old fields again in the UPDATE. A concurrent edit causes the whole
  transaction to roll back. Verify the entire season's model-value digest after
  the update and before commit. No model value is overwritten.

The core-stat commitment format is unchanged: it covers player/game/date/team
and points/rebounds/assists. The additional recovery audit compares all stored
model fields, including minutes, and commits their aggregate digest. It does not
retroactively prove what was available before the historical games.

## Verification

42 focused parser, ingestion, and recovery tests passed locally, covering audit
no-writes, safe application, preserved zero values, canonical labels, idempotency,
existing/partial hash protection, timestamp-only recovery, newer-observation
protection, mismatched stats/workload/identity,
malformed sources, and rollback after a concurrent change. A disposable PostgreSQL
regression is part of the existing CI worker test gate.

PR #204 passed 1,000 backend tests, 9 migration tests, 24 PostgreSQL/storage
checks, and the frontend/worker/security gates. The production release
[35908902758](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/35908902758)
completed successfully.

The first production application returned a database OperationalError and rolled
back. A separate database count confirmed **zero** source hashes in both seasons;
no partial season was committed. Diagnosis with read-only EXPLAIN found a scaling
defect: `IS NOT DISTINCT FROM` on the non-null player/game identities produces a
sequential scan (estimated total cost 2016.75) for every recovery row. Equality on
those same identities uses the existing unique index (estimated cost 2.51).

The follow-up keeps every optimistic value/provenance comparison and uses equality
only for the two non-null identities. A 2,048-row PostgreSQL case verifies the
actual recovery UPDATE has indexed identity conditions, all values survive, the
source constraint validates, and a repeat application is idempotent. The original
two-row case remains. Recovery is pending verification of this follow-up. This work makes no provider quote
requests, changes no credit limits, and involves no purchase, card, subscription,
bet, model/threshold change, frozen-cohort refit, or synthetic prediction.
