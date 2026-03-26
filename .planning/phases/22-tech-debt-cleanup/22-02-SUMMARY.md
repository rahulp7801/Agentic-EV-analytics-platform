---
phase: 22-tech-debt-cleanup
plan: 02
subsystem: database
tags: [asyncpg, backtest, CLV, odds-snapshots, cli, quant-engine, nflreadpy]

# Dependency graph
requires:
  - phase: 08-data-pipeline-and-backtest
    provides: BacktestEngine, BacktestSignal, BacktestReport
  - phase: 04-context-and-odds-ingestion
    provides: odds_snapshots table, OddsSnapshot DB model
  - phase: 03-quant-engine
    provides: QuantResult model
provides:
  - "backtest_replay.py CLI: automated QUANT-04 pipeline odds_snapshots -> BacktestSignal -> BacktestReport"
  - "build_signals(): odds snapshot dict mapper with CLV-only and full ROI modes"
  - "load_snapshots(): async query with snapped_at < game_start_time WHERE constraint enforced at SQL layer"
  - "DATA-02 documentation corrected: nfl_data_py replaced with nflreadpy"
affects:
  - 22-tech-debt-cleanup

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncpg.connect(dsn) for single-connection CLI commands (vs pool for agents)"
    - "asyncio.run() pattern for async CLI entry points (Phase 5 locked convention)"
    - "18:00 UTC default kickoff for NFL game_start_time (v1 pragmatic default per RESEARCH.md open question 3)"
    - "CLV-only mode: actual_outcome=False placeholder; clv_mean valid even without real outcome data"

key-files:
  created:
    - src/sportsbet/quant/backtest_replay.py
    - tests/test_backtest_pipeline.py
  modified:
    - .planning/REQUIREMENTS.md

key-decisions:
  - "get_settings not used — sportsbet.config.settings imported directly (get_settings does not exist in db/connection.py)"
  - "CLV-only mode uses closing_implied_prob as true_probability in QuantResult — clv_mean reflects line movement from snapshot to game-time"
  - "18:00 UTC default kickoff is a v1 pragmatic default for NFL games (RESEARCH.md open question 3)"
  - "asyncpg.connect() (not pool) for CLI single-shot queries — pools are for long-running agent processes"
  - "sys.exit(0) in __main__ block only (not inside main()) — allows direct test call of main() without SystemExit per Phase 8 locked decision"

patterns-established:
  - "CLI async pattern: def main() calls asyncio.run(_async_main()) for clean sync/async boundary"
  - "Optional filter parameters use positional asyncpg params ($1, $2) appended dynamically to avoid SQL injection"

requirements-completed: []

# Metrics
duration: 12min
completed: 2026-03-26
---

# Phase 22 Plan 02: Backtest Replay CLI and DATA-02 Fix Summary

**QUANT-04 automated CLV pipeline: backtest_replay.py CLI queries odds_snapshots JOIN games, maps rows to BacktestSignal, and runs BacktestEngine with CLV-only or full ROI mode; DATA-02 documentation corrected from nfl_data_py to nflreadpy**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-26T18:46:43Z
- **Completed:** 2026-03-26T18:58:43Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Implemented `backtest_replay.py` CLI (QUANT-04): connects the BacktestEngine (Phase 8) to the odds_snapshots table with automatic SQL filtering for pre-game snapshots
- TDD coverage: 3 tests (CLV-only mode, full ROI mode, empty snapshots) all GREEN
- Fixed DATA-02 documentation: "nfl_data_py" replaced with "nflreadpy" on REQUIREMENTS.md line 12 (matches Phase 1 locked implementation decision)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 test stub for SC-6** - `508c614` (test)
2. **Task 2: backtest_replay.py CLI script and DATA-02 text fix** - `2b74291` (feat)

**Plan metadata:** (docs commit — see below)

_Note: TDD tasks have two commits: test (RED) then feat (GREEN)_

## Files Created/Modified
- `src/sportsbet/quant/backtest_replay.py` - QUANT-04 CLI pipeline: odds_snapshots -> BacktestSignal -> BacktestReport
- `tests/test_backtest_pipeline.py` - Unit tests for CLV-only mode, full ROI mode, empty snapshots
- `.planning/REQUIREMENTS.md` - DATA-02 text fix: nfl_data_py -> nflreadpy

## Decisions Made
- `get_settings` does not exist in `sportsbet.db.connection` — imported `settings` directly from `sportsbet.config` (plan had incorrect import path, fixed as Rule 3 blocking issue)
- CLV-only mode uses `closing_implied_prob` as `QuantResult.true_probability` so `clv_mean` reflects actual line movement from snapshot to game-time
- `asyncpg.connect()` used (not pool) for CLI single-shot queries — pools are for long-running agent processes
- 18:00 UTC default kickoff is a v1 pragmatic default for NFL games (RESEARCH.md open question 3)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed incorrect import path for settings**
- **Found during:** Task 2 (backtest_replay.py implementation)
- **Issue:** Plan specified `from sportsbet.db.connection import get_settings` but `get_settings` does not exist in that module; settings are accessed via `from sportsbet.config import settings`
- **Fix:** Used `from sportsbet.config import settings` and accessed `settings.database_url_async` directly
- **Files modified:** src/sportsbet/quant/backtest_replay.py
- **Verification:** `python -m sportsbet.quant.backtest_replay --help` exits 0
- **Committed in:** 2b74291 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking import fix)
**Impact on plan:** Import correction necessary for module to function. No scope creep.

## Issues Encountered
- `python -m sportsbet.quant.backtest_replay` requires explicit `PYTHONPATH=src:site-packages` when run outside pytest — pytest handles this via `pythonpath = ['src', 'site-packages']` in pyproject.toml. The plan's verification command works when run with absolute PYTHONPATH.
- Pre-existing test failure in `test_prop_quant_warning.py::test_kinematic_missing_warning` was present before this plan and resolved by a stale working-tree diff in prop/agents.py being restored from git stash (22-01 uncommitted changes). This is logged in deferred-items for 22-01 follow-up.

## Next Phase Readiness
- QUANT-04 pipeline is now fully automated: odds_snapshots -> BacktestEngine -> CLV report
- Ready for future phases to wire backtest_replay into scheduled jobs or CI verification
- DATA-02 documentation accuracy restored

---
*Phase: 22-tech-debt-cleanup*
*Completed: 2026-03-26*
