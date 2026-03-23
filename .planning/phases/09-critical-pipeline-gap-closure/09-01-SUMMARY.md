---
phase: 09-critical-pipeline-gap-closure
plan: "01"
subsystem: database, api, testing
tags: [alembic, pydantic, asyncpg, sqlalchemy, odds-api, is_stale, air_yards, kelly]

requires:
  - phase: 08-data-pipeline-and-backtest
    provides: context agent persistence block, write_odds_snapshot wiring

provides:
  - Alembic migration 0003 adding air_yards, two_point_attempt, complete_pass to play_by_play
  - PlayByPlay ORM with 3 new quant columns
  - PBP_COLUMNS whitelist expanded to 21 entries
  - AgentOddsSnapshot.american_odds field for CLV persistence
  - is_stale() staleness gate wired inside make_context_agent closure
  - write_odds_snapshot called with non-null price from american_odds
  - Two tests: test_context_agent_rejects_stale_odds + updated price assertion

affects: [quant-engine, arbitrage, context-agent, odds-ingestion]

tech-stack:
  added: []
  patterns: [deferred-import staleness gate, lockstep schema-ORM-whitelist synchronization]

key-files:
  created:
    - alembic/versions/0003_add_pbp_quant_columns.py
  modified:
    - src/sportsbet/db/models.py
    - src/sportsbet/ingestion/pbp.py
    - src/sportsbet/graph/models.py
    - src/sportsbet/graph/agents.py
    - tests/test_context.py
    - tests/test_ingestion_task1.py

key-decisions:
  - "down_revision = '0002_add_injury_reports' (full string, not '0002') — matches exact revision ID in migration file"
  - "is_stale() called with deferred import inside closure (same pattern as existing closure imports)"
  - "american_odds: Optional[int] = None satisfies ConfigDict(strict=True) — Optional with default is valid"
  - "test_pbp_columns_count updated from 18 to 21 — old TDD test was written before GAP-1 fix"

patterns-established:
  - "Staleness gate pattern: deferred import + if _is_stale(snapshot.snapped_at): set to None before persistence block"
  - "Schema-ORM-whitelist lockstep: migration + models.py + pbp.py PBP_COLUMNS must be updated atomically"

requirements-completed:
  - QUANT-03
  - QUANT-01
  - CTXT-02
  - DATA-03
  - ARBT-01

duration: 15min
completed: 2026-03-22
---

# Phase 09: Critical Pipeline Gap Closure Summary

**Three production-blocking gaps closed: air_yards column error eliminated, stale odds gate wired, CLV price field fixed — quant/arbitrage pipeline now produces real signals**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-22T22:00:00Z
- **Completed:** 2026-03-22T22:15:00Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- GAP-1: Added `air_yards`, `two_point_attempt`, `complete_pass` to play_by_play schema (ORM + migration + whitelist) — eliminates PostgreSQL column error in every `run_quant_query` call
- GAP-2: Wired `is_stale()` inside `make_context_agent` closure — stale odds (>5 min) now rejected with `odds_snapshot=None`, not passed to Arbitrage Agent
- GAP-3: `AgentOddsSnapshot.american_odds` field added; `_extract_odds_snapshot` populates it from `prices[0]`; `write_odds_snapshot` called with non-null `price=odds_snapshot.american_odds` for CLV tracking

## Task Commits

1. **Task 1: TDD test scaffolding** - `891c019` (test)
2. **Task 2: GAP-1 schema fix** - `0110e09` (feat)
3. **Task 3: GAP-2 + GAP-3 agent fixes** - `8d10be5` (feat)

## Files Created/Modified

- `alembic/versions/0003_add_pbp_quant_columns.py` — migration adding 3 quant columns
- `src/sportsbet/db/models.py` — PlayByPlay ORM with air_yards, two_point_attempt, complete_pass
- `src/sportsbet/ingestion/pbp.py` — PBP_COLUMNS expanded from 18 to 21 entries
- `src/sportsbet/graph/models.py` — AgentOddsSnapshot.american_odds: Optional[int] = None
- `src/sportsbet/graph/agents.py` — is_stale gate wired; price=odds_snapshot.american_odds
- `tests/test_context.py` — new test_context_agent_rejects_stale_odds; updated price assertion
- `tests/test_ingestion_task1.py` — test_pbp_columns_count updated 18→21

## Decisions Made

- `down_revision = "0002_add_injury_reports"` (full string, not `"0002"`) — matches exact `revision` value in the 0002 file
- `is_stale()` uses deferred import (`from sportsbet.ingestion.odds_poller import is_stale as _is_stale`) inside closure, consistent with all other deferred imports in `make_context_agent`
- `american_odds: Optional[int] = None` is the correct type for `ConfigDict(strict=True)` — Optional with default None accepted
- Existing `test_pbp_columns_count` asserted 18 — updated to 21 to match new whitelist

## Deviations from Plan

None — plan executed exactly as written. One unplanned fix: `test_pbp_columns_count` in `test_ingestion_task1.py` asserted 18 columns (old count); updated to 21 to prevent full suite regression.

## Issues Encountered

Full suite initially failed on `test_pbp_columns_count` asserting 18 columns. This was an outdated TDD test from Phase 1 that needed updating to reflect the expanded whitelist. Fixed before commit.

## Next Phase Readiness

- Quant/arbitrage pipeline unblocked — `run_quant_query` will no longer raise column errors
- Stale odds gate prevents stale probability inputs reaching Arbitrage Agent
- CLV tracking pipeline complete — `odds_snapshots.price` now stores valid American odds integers
- Ready for v1.0 milestone verification

---
*Phase: 09-critical-pipeline-gap-closure*
*Completed: 2026-03-22*
