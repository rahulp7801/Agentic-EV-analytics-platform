---
phase: 08-data-pipeline-and-backtest
plan: 01
subsystem: database
tags: [postgresql, asyncpg, sqlalchemy, pydantic, langgraph, backtest, kinematic, odds]

# Dependency graph
requires:
  - phase: 04-context-and-odds-ingestion
    provides: write_odds_snapshot, OddsSnapshotCreate, make_context_agent closure
  - phase: 06-kinematic-agent
    provides: _SEPARATION_QUERY, run_matchup_query, KinematicAnalysis
  - phase: 03-quant-engine
    provides: BacktestEngine, BacktestSignal, BacktestReport
provides:
  - Live odds snapshots persisted to PostgreSQL from context agent for CLV tracking (DATA-03)
  - avg_time_to_throw returned by kinematic separation query via QB LEFT JOIN (KINE-01)
  - BacktestEngine accessible via python -m sportsbet.quant.backtest CLI (QUANT-04)
affects:
  - CLV tracking queries (odds_snapshots table now populated from context agent)
  - Kinematic analysis callers expecting non-None avg_time_to_throw when QB NGS data exists

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Lazy engine initialization with connect_timeout=5 inside closure — avoids DB hang in tests
    - Module-level imports of DB helpers for unittest.mock patchability
    - QB LEFT JOIN subquery pattern for stat_type='passing' cross-join in asyncpg queries
    - CLI entry point via main() + if __name__ == '__main__' block; sys.exit in __main__ only

key-files:
  created: []
  modified:
    - src/sportsbet/graph/agents.py
    - src/sportsbet/kinematic/matchup.py
    - src/sportsbet/quant/backtest.py
    - tests/test_context.py
    - tests/test_kinematic.py
    - tests/test_backtest.py

key-decisions:
  - "get_sync_engine and write_odds_snapshot imported at module level in agents.py for unittest.mock patchability — closure-scoped imports cannot be patched via sportsbet.graph.agents.name"
  - "Lazy engine init in persistence block with connect_timeout=5 — avoids indefinite hang in tests that call make_context_agent without patching get_sync_engine"
  - "sys.exit(0) in __main__ block only (not inside main()) — allows direct call from tests without SystemExit propagation"
  - "QB LEFT JOIN subquery on ngs_stats WHERE stat_type='passing' groups by team_abbr/season — one avg_time_to_throw per team per season, LEFT JOIN produces NULL when no QB rows exist"

patterns-established:
  - "Lazy DB engine init pattern: _sync_engine_cache list as mutable container inside closure, initialized on first invocation with connect_timeout"
  - "Module-level import of DB/ingestion helpers in agents.py enables clean unit test patching without module reload"
  - "main() function as pure logic entry point; sys.exit() deferred to __main__ guard for testability"

requirements-completed:
  - QUANT-04
  - DATA-03
  - KINE-01

# Metrics
duration: 30min
completed: 2026-03-22
---

# Phase 08 Plan 01: Data Pipeline and Backtest Gaps Summary

**Three surgical fixes closing v1.0 gaps: odds snapshot persistence to PostgreSQL from context agent, QB avg_time_to_throw via LEFT JOIN in kinematic query, and BacktestEngine CLI entry point**

## Performance

- **Duration:** 30 min
- **Started:** 2026-03-22T20:55:19Z
- **Completed:** 2026-03-22T21:25:00Z
- **Tasks:** 4 (TDD: RED stubs + 3 GREEN implementations)
- **Files modified:** 6

## Accomplishments

- DATA-03: `make_context_agent` now persists live odds snapshots to `odds_snapshots` table via `write_odds_snapshot` after each successful fetch, enabling CLV tracking across sessions
- KINE-01: `_SEPARATION_QUERY` LEFT JOINs QB passing rows on `team_abbr + season` so `avg_time_to_throw` is non-None when QB NGS data exists for the receiver's team
- QUANT-04: `python -m sportsbet.quant.backtest` exits 0 and prints `sample_size`, `hit_rate`, `roi`, `clv_mean` using a 5-signal fixture; `main()` callable directly from tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — add test stubs for all three gaps** - `3d8af4d` (test)
2. **Task 2: Wire write_odds_snapshot into make_context_agent (DATA-03)** - `76ed73e` (feat)
3. **Task 3: Fix _SEPARATION_QUERY to include avg_time_to_throw via QB LEFT JOIN (KINE-01)** - `8800fd7` (feat)
4. **Task 4: Add BacktestEngine CLI entry point to backtest.py (QUANT-04)** - `3926206` (feat)

## Files Created/Modified

- `src/sportsbet/graph/agents.py` - Added module-level imports of `get_sync_engine`, `write_odds_snapshot`, `OddsSnapshotCreate`; persistence block with lazy engine init inside `make_context_agent`
- `src/sportsbet/kinematic/matchup.py` - Replaced `_SEPARATION_QUERY` with QB LEFT JOIN version that adds `avg_time_to_throw` column
- `src/sportsbet/quant/backtest.py` - Added `main()` function with fixture dataset and `if __name__ == '__main__': main()` guard
- `tests/test_context.py` - Added `test_context_agent_persists_odds_snapshot`
- `tests/test_kinematic.py` - Added `test_matchup_query_returns_avg_time_to_throw`
- `tests/test_backtest.py` - Added `test_backtest_cli_main_prints_output`

## Decisions Made

- **Module-level imports for patchability:** `get_sync_engine` and `write_odds_snapshot` must be importable as `sportsbet.graph.agents.write_odds_snapshot` for `unittest.mock.patch` to work. Closure-scoped lazy imports are not patchable by external tests.
- **Lazy engine with connect_timeout=5:** The existing `test_context_agent_updates_graphstate` does not patch `write_odds_snapshot`, so the real function would be called when `odds_snapshot is not None`. A `connect_timeout=5` prevents the test from hanging indefinitely when no PostgreSQL server is available.
- **`sys.exit(0)` in `__main__` only:** Placing `sys.exit(0)` inside `main()` causes `SystemExit: 0` to propagate in tests. The fix: `main()` returns normally; `sys.exit(0)` is only called from the `if __name__ == '__main__'` block.
- **QB subquery pattern:** `avg_time_to_throw` is a passing-specific field (stat_type='passing') on QB rows. The existing code at line 112 already calls `row.get("avg_time_to_throw")` — the column simply needed to appear in SELECT via LEFT JOIN. NULL from LEFT JOIN when no QB data exists is correctly handled by the existing `Optional[Decimal]` wrapping.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Module-level imports required for test patchability**
- **Found during:** Task 2 (Wire write_odds_snapshot into make_context_agent)
- **Issue:** Plan specified closure-scoped imports (`from sportsbet.db.connection import get_sync_engine` inside `make_context_agent` body). The test patches `sportsbet.graph.agents.get_sync_engine` — this requires the name to exist as a module-level attribute of `agents.py`. Closure-scoped imports don't create module-level attributes, causing `AttributeError: <module 'sportsbet.graph.agents'> does not have the attribute 'get_sync_engine'`.
- **Fix:** Moved `get_sync_engine`, `write_odds_snapshot`, and `OddsSnapshotCreate` imports to module level in `agents.py`. Removed duplicate closure-scoped imports.
- **Files modified:** `src/sportsbet/graph/agents.py`
- **Verification:** `test_context_agent_persists_odds_snapshot` PASSED
- **Committed in:** `76ed73e` (Task 2 commit)

**2. [Rule 1 - Bug] Lazy engine init with connect_timeout to prevent test hang**
- **Found during:** Task 2 (Wire write_odds_snapshot into make_context_agent)
- **Issue:** Plan specified creating `_sync_engine = get_sync_engine()` at closure construction time. However, the existing test `test_context_agent_updates_graphstate` calls `make_context_agent` without patching `get_sync_engine`, so any DB call would hang. Even with lazy init, the `write_odds_snapshot` call inside `context_agent` would try to `engine.begin()` with no PostgreSQL available, hanging indefinitely.
- **Fix:** Used `_sync_engine_cache: list = []` mutable container and created the engine lazily on first invocation with `connect_args={"connect_timeout": 5}`. This bounds the hang to 5 seconds max instead of infinite wait.
- **Files modified:** `src/sportsbet/graph/agents.py`
- **Verification:** All 9 `test_context.py` tests pass (previously 2 integration tests hung)
- **Committed in:** `76ed73e` (Task 2 commit)

**3. [Rule 1 - Bug] sys.exit(0) moved from main() to __main__ block**
- **Found during:** Task 4 (Add BacktestEngine CLI entry point)
- **Issue:** Plan specified `sys.exit(0)` inside `main()`. When the test calls `main()` directly, `SystemExit: 0` propagates and pytest reports `FAILED`.
- **Fix:** Removed `sys.exit(0)` from inside `main()`. Added it to the `if __name__ == '__main__':` block only. `main()` now returns `None` cleanly.
- **Files modified:** `src/sportsbet/quant/backtest.py`
- **Verification:** `test_backtest_cli_main_prints_output` PASSED; `python -m sportsbet.quant.backtest` still exits 0
- **Committed in:** `3926206` (Task 4 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 1 - Bug)
**Impact on plan:** All three fixes were necessary for correctness. No new dependencies, no scope creep. The functional behavior (odds persisted, avg_time_to_throw returned, CLI exits 0) is exactly as specified.

## Issues Encountered

- Test `test_matchup_query_returns_avg_time_to_throw` was GREEN at the RED phase (not truly red) — the existing code at line 112 already handled `row.get("avg_time_to_throw")` correctly from the mock dict. The query fix (Task 3) ensures the real PostgreSQL query actually returns this column. The mock-based test already passes because it directly provides the value in the mock row dict.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three v1.0 requirements (QUANT-04, DATA-03, KINE-01) are now closed
- The `odds_snapshots` table will be populated on each context agent run when live odds are available, enabling CLV tracking queries
- `python -m sportsbet.quant.backtest` provides a smoke test for BacktestEngine import and functionality
- 86 tests passing, 9 skipped (DB-gated integration tests), 0 failures

## Self-Check: PASSED

All files exist and all task commits verified:
- FOUND: src/sportsbet/graph/agents.py
- FOUND: src/sportsbet/kinematic/matchup.py
- FOUND: src/sportsbet/quant/backtest.py
- FOUND: .planning/phases/08-data-pipeline-and-backtest/08-01-SUMMARY.md
- FOUND commit: 3d8af4d (test stubs)
- FOUND commit: 76ed73e (DATA-03 implementation)
- FOUND commit: 8800fd7 (KINE-01 implementation)
- FOUND commit: 3926206 (QUANT-04 implementation)

---
*Phase: 08-data-pipeline-and-backtest*
*Completed: 2026-03-22*
