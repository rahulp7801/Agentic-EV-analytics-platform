---
phase: 03-quant-engine
plan: "03"
subsystem: testing
tags: [backtesting, pandas, dataclasses, structlog, kelly-criterion, clv, roi]

# Dependency graph
requires:
  - phase: 03-quant-engine
    provides: QuantResult (graph/models.py), vig.py devig functions for closing_implied_prob
  - phase: 02-agent-infrastructure
    provides: GraphState, agent node patterns, LangGraph skeleton
provides:
  - BacktestSignal dataclass — typed signal record pairing QuantResult with closing line and outcome
  - BacktestReport dataclass — roi, hit_rate, clv_mean, sample_size, signals_df with closing_line_note
  - BacktestEngine.run() — vectorized pandas backtest replay with null-probability filtering and structlog warning
  - 6 unit tests in tests/test_backtest.py covering ROI fixture, empty signals, CLV sign, signals_df, exact ROI, null skip
affects: [04-arbitrage-agent, 05-parlay-builder, cli-tooling]

# Tech tracking
tech-stack:
  added: [pandas (DataFrame vectorized ops in backtest module), structlog (null-probability warning)]
  patterns:
    - Standalone offline module isolation — BacktestEngine never imported from graph.py or any agent node
    - Null-probability guard before DataFrame construction — filter + structlog.warning + graceful degradation
    - closing_line_note field on BacktestReport — documents pre-game snapshot constraint without DB enforcement
    - make_signals() fixture builder at module level in test file — reusable across all 6 test cases

key-files:
  created:
    - src/sportsbet/quant/backtest.py
    - tests/test_backtest.py
  modified: []

key-decisions:
  - "BacktestEngine is standalone offline module — never imported from graph.py or any agent node; isolation documented in module docstring"
  - "closing_line_note as BacktestReport field (not docstring only) — makes pre-game snapshot constraint machine-readable to callers"
  - "structlog.warning('skipping_null_probability_signal') per skipped signal — consistent with existing logger pattern in quant layer"
  - "caplog.at_level(logging.WARNING) in test_backtest_skips_null_probability_signal — structlog warning captured by pytest caplog via stdlib logging bridge"

patterns-established:
  - "Offline analytics module pattern: dataclasses + pandas + standalone module with no graph imports"
  - "TDD RED-then-GREEN: stub tests with raise AssertionError committed first, then module implemented to pass"

requirements-completed: [QUANT-04]

# Metrics
duration: 3min
completed: 2026-03-13
---

# Phase 3 Plan 03: Backtest Module Summary

**Vectorized pandas backtesting engine (BacktestEngine) with ROI, hit-rate, and CLV metrics — standalone offline module, fully isolated from LangGraph graph layer**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-13T19:29:31Z
- **Completed:** 2026-03-13T19:32:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- BacktestSignal + BacktestReport dataclasses with full typing and closing_line_note documentation field
- BacktestEngine.run() with empty-list guard, null-probability filtering with structlog warning, vectorized pandas ROI/hit_rate/CLV
- 6 TDD tests passing: fixture ROI (0.1454 exact), empty signals (no ZeroDivisionError), CLV sign check, signals_df type, exact ROI spot-check, null probability skip with sample_size adjustment
- Full suite green: 51 passed, 9 skipped (added 6 new tests vs previous 45 passed)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — failing test stubs for QUANT-04** - `7de184b` (test)
2. **Task 2: backtest.py — BacktestSignal, BacktestReport, BacktestEngine GREEN** - `4f64d24` (feat)

**Plan metadata:** (docs: complete plan — this commit)

_Note: TDD tasks have two commits — RED test stubs then GREEN implementation_

## Files Created/Modified

- `src/sportsbet/quant/backtest.py` — BacktestSignal, BacktestReport dataclasses and BacktestEngine class with vectorized pandas ops
- `tests/test_backtest.py` — 6 unit tests with make_signals() fixture builder; no DB or asyncpg dependency

## Decisions Made

- BacktestEngine isolated as offline module — no import from graph.py enforced by module docstring and plan must_have
- closing_line_note added as a BacktestReport dataclass field (not just docstring) so callers have programmatic access to the pre-game snapshot constraint
- structlog warning emitted per skipped null-probability signal, consistent with existing quant layer logging pattern
- caplog.at_level(logging.WARNING) used in the null-probability test — structlog routes through stdlib logging bridge, so pytest caplog captures it correctly

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- QUANT-04 closes the quant pipeline loop — backtesting replay is now available for offline evaluation of QuantResult signal quality
- BacktestEngine can be wired to a CLI tool or Jupyter notebook for historical analysis against Phase 1 database data
- Phase 4 (arbitrage agent) can use BacktestReport metrics as signal quality filters before flagging +EV opportunities

## Self-Check: PASSED

- src/sportsbet/quant/backtest.py: FOUND
- tests/test_backtest.py: FOUND
- .planning/phases/03-quant-engine/03-03-SUMMARY.md: FOUND
- Commit 7de184b (test RED stubs): FOUND
- Commit 4f64d24 (feat GREEN implementation): FOUND

---
*Phase: 03-quant-engine*
*Completed: 2026-03-13*
