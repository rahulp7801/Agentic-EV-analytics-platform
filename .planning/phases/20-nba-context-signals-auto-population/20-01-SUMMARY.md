---
phase: 20-nba-context-signals-auto-population
plan: 01
subsystem: database
tags: [asyncpg, pydantic, langgraph, nba, tdd, decimal]

# Dependency graph
requires:
  - phase: 12-nba-player-prop-quant-engine
    provides: NBAContextSignals model and _apply_nba_context_adjustments pipeline
  - phase: 18-situational-game-log-prop-queries
    provides: nba_player_gamelogs table with team_abbreviation and game_date columns
  - phase: 19-critical-integration-fixes
    provides: INT-2/INT-3 integration gap documentation (nba_context_signals always None)
provides:
  - make_nba_context_signals_producer closure factory (nba_context_producer.py)
  - 6 passing TDD tests covering happy path, cold DB, B2B detection, invalid player_id, Decimal wrapping, None opp stats
  - LangGraph-compatible async node that auto-populates GraphState.nba_context_signals before make_nba_quant_agent runs
affects:
  - 20-02 (integration wiring plan: registers producer as graph node)
  - 20-03 (integration test plan: validates end-to-end NBA prop pipeline with real context)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Closure factory pattern (pool + target_date injected at construction, Phase 8 pattern)
    - MagicMock pool pattern for asyncpg (Phase 4 locked — MagicMock not AsyncMock for pool.acquire)
    - Decimal(str(round(x, 6))) wrapping for all float->Decimal conversions (Phase 3 locked)
    - max(0, (today - last_game_date).days - 1) rest_days formula (B2B = 0, yesterday = 0 rest days)
    - League-average fallback for empty/invalid player_id and cold DB paths

key-files:
  created:
    - src/sportsbet/prop/nba_context_producer.py
    - tests/test_nba_context_producer.py
  modified: []

key-decisions:
  - "rest_days formula: max(0, (today - last_game_date).days - 1) — yesterday (1 day ago) = 0 rest days (back-to-back)"
  - "opponent_def_rating derived from nba_player_stats scoring proxy: LEAGUE_AVG_DEF_RATING * (avg_pts / 8.0), clamped [90, 140], wrapped as Decimal"
  - "pace_factor = LEAGUE_AVG_PACE (1.0 ratio) — no possession data in v1 schema; neutral placeholder"
  - "is_home derived from GraphState home_team/away_team comparison — no extra DB query"
  - "Empty receiver_gsis_id short-circuits to league-average defaults without touching DB"
  - "player_id_raw cast to int() before asyncpg query — prevents DataError on INTEGER column"
  - "Cold DB path (no gamelog rows) returns rest_days=1, is_home=False, league-average def_rating and pace"

patterns-established:
  - "Pattern 1: NBA context producer uses two fetchrow calls within single pool.acquire() context — minimizes connection pool pressure"
  - "Pattern 2: _league_avg_signals() helper centralizes fallback NBAContextSignals construction — single source of truth for defaults"

requirements-completed: [PROP-05, NBA-02]

# Metrics
duration: 15min
completed: 2026-03-26
---

# Phase 20 Plan 01: NBA Context Signals Producer Summary

**make_nba_context_signals_producer closure factory that reads nba_player_gamelogs and nba_player_stats to auto-populate NBAContextSignals in GraphState before the NBA prop quant agent runs, closing INT-3 gap**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-26T14:30:00Z
- **Completed:** 2026-03-26T14:46:33Z
- **Tasks:** 2 (TDD: RED phase + GREEN phase)
- **Files modified:** 2

## Accomplishments
- Implemented make_nba_context_signals_producer as a LangGraph-compatible async closure factory with pool and target_date injected at construction time
- Closed INT-3 gap: nba_context_signals is now automatically populated from nba_player_gamelogs + nba_player_stats before make_nba_quant_agent runs, enabling the four-stage adjustment pipeline (pace, def_rating, rest, home) to receive real data instead of None
- 6 TDD tests covering all critical paths: happy path B2B detection, cold DB fallback, 3-days-ago rest_days=2, empty player_id short-circuit, Decimal clamping to 140, None opponent stats fallback

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — test stubs for nba_context_producer** - `d18a246` (test)
2. **Task 2: Implement make_nba_context_signals_producer (GREEN phase)** - `f01d5c2` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD tasks have two commits — test (RED) then feat (GREEN)_

## Files Created/Modified
- `src/sportsbet/prop/nba_context_producer.py` - Closure factory implementing make_nba_context_signals_producer with DB queries, rest_days computation, Decimal clamping, and league-average fallback paths
- `tests/test_nba_context_producer.py` - 6 async TDD tests covering all contract invariants

## Decisions Made
- rest_days formula max(0, days - 1) matches NBA B2B semantics: yesterday = 0 rest days (game today after game yesterday is a back-to-back)
- opponent_def_rating uses nba_player_stats avg points per player as scoring proxy for defensive rating, clamped to [90, 140] to prevent extreme values from distorting probability adjustments
- pace_factor hardcoded to LEAGUE_AVG_PACE (Decimal("100.0")) — v1 schema has no possession-per-48 data, so neutral 1.0 ratio is the correct default
- Both DB queries executed within single pool.acquire() context to minimize connection overhead

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- make_nba_context_signals_producer is ready to be registered as a LangGraph graph node in Phase 20 Plan 02
- The producer's return dict {"nba_context_signals": NBAContextSignals} matches GraphState.nba_context_signals type annotation exactly
- Full test suite green: 199 passed, 11 skipped (DB-gated), 2 xfailed — no regressions

## Self-Check: PASSED
- FOUND: src/sportsbet/prop/nba_context_producer.py
- FOUND: tests/test_nba_context_producer.py
- FOUND: d18a246 (test commit)
- FOUND: f01d5c2 (feat commit)
- All 6 tests in test_nba_context_producer.py pass
- Full suite 199 passed, no regressions

---
*Phase: 20-nba-context-signals-auto-population*
*Completed: 2026-03-26*
