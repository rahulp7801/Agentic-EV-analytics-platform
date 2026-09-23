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

During the new tool's read-only audit, the 26,651 rows for 2025 already had
provenance from another refresh. The planner protected those rows and proposed
only 26,306 prior-season repairs, including the 198 official name labels.
The exact plan and source hashes are in `2026-09-23-nba-provenance-plan.json`.
The source observation times are September 23, 2026; nothing is backdated to the
historical games or original research period.

## Recovery implementation

`sportsbet.ingestion.nba_provenance` downloads the free official season endpoint.
Its default mode is a read-only audit; `--apply` explicitly enables recovery.

- Validate official regular-season/base/totals scope, requested season, bounded
  response size, unique player/game identities, dates, matchup, and valid stats.
- Compare every stored model value to the normalized official response. Playing
  time uses PostgreSQL's existing one-decimal storage precision.
- Update only rows from `nba` with all three provenance fields missing. Existing
  or partial provenance, other providers, missing source rows, and changed model
  values are excluded and counted.
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

39 focused parser, ingestion, and recovery tests passed locally, covering audit
no-writes, safe application, preserved zero values, canonical labels, idempotency,
existing/partial provenance protection, mismatched stats/workload/identity,
malformed sources, and rollback after a concurrent change. A disposable PostgreSQL
regression is part of the existing CI worker test gate.

Production application is pending full CI. This work makes no provider quote
requests, changes no credit limits, and involves no purchase, card, subscription,
bet, model/threshold change, frozen-cohort refit, or synthetic prediction.
