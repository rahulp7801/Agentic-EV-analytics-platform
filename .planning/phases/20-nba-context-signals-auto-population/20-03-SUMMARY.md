---
phase: 20-nba-context-signals-auto-population
plan: 03
subsystem: testing
tags: [asyncio, pytest, pydantic, nba, context-signals, mock, integration-test, decimal]

# Dependency graph
requires:
  - phase: 20-01
    provides: make_nba_context_signals_producer factory and NBAContextSignals model
  - phase: 20-02
    provides: nba_context_producer wired into LangGraph graph before nba_quant_agent
  - phase: 12-nba-player-prop-quant-engine
    provides: make_nba_quant_agent and _apply_nba_context_adjustments four-stage pipeline

provides:
  - tests/test_nba_context_integration.py with two passing async integration tests
  - ROADMAP Phase 20 Success Criterion 5 satisfied (INT-3 fully closed with observable proof)
  - test_context_signals_adjust_probability: producer->agent pipeline produces different probability from baseline
  - test_none_signals_returns_baseline: regression guard confirming None path is stable

affects: [ROADMAP phase-20 SC-5, INT-3 closure verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - MagicMock pool pattern for asyncpg producer (Phase 4 locked — two fetchrow side_effects)
    - patch("sportsbet.prop.nba_agents.run_nba_prop_query") — consumer-module patching (Phase 8 pattern)
    - Decimal("0.55") not float for strict=True Pydantic PropResult fields
    - asyncio_mode="auto" bare async def — no @pytest.mark.asyncio decorator
    - Deterministic base PropResult isolates signal path from NormalDist query engine

key-files:
  created:
    - tests/test_nba_context_integration.py
  modified: []

key-decisions:
  - "patch target is sportsbet.prop.nba_agents.run_nba_prop_query (consumer module, not origin) — Phase 8 patching pattern"
  - "agent_pool = MagicMock() (separate from producer_pool) — agent's pool not reached because run_nba_prop_query is patched before DB call"
  - "target_date=date(2024, 11, 20) passed explicitly to make_nba_context_signals_producer — avoids date.today() non-determinism in tests"
  - "Decimal('0.55') and Decimal('0.42') used for BASE_PROB — PropResult strict=True rejects raw float"

patterns-established:
  - "Pattern 1: Producer-agent isolation in integration tests — mock producer pool + patch agent query fn = fully offline two-phase verification"
  - "Pattern 2: ROADMAP SC assertion pairing — adjusted != BASE_PROB AND adjusted != baseline in same test function proves pipeline fired"

requirements-completed: [PROP-05, NBA-02]

# Metrics
duration: 4min
completed: 2026-03-26
---

# Phase 20 Plan 03: NBA Context Integration Test Summary

**Two async offline integration tests prove NBAContextSignals producer-to-agent pipeline produces a different probability from the unadjusted baseline, closing ROADMAP Phase 20 Success Criterion 5**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-26T17:14:11Z
- **Completed:** 2026-03-26T17:18:00Z
- **Tasks:** 1 of 1
- **Files modified:** 1

## Accomplishments

- Created `tests/test_nba_context_integration.py` with two passing async integration tests covering the full NBAContextSignals pipeline end-to-end
- `test_context_signals_adjust_probability`: producer with LAL home team, B2B rest (rest_days=0), and above-average opponent scoring (avg_pts=12.0) emits NBAContextSignals -> agent applies four-stage adjustments -> adjusted probability != Decimal("0.55") baseline AND != None-baseline result (ROADMAP SC 5)
- `test_none_signals_returns_baseline`: regression guard confirms None-signals path returns Decimal("0.42") unchanged with data_source="postgresql", no adjustments applied
- Both tests fully offline: producer pool uses MagicMock with two sequential fetchrow returns; agent uses patched run_nba_prop_query — no live DB required

## Task Commits

Each task was committed atomically:

1. **Task 1: Create end-to-end integration test for NBAContextSignals pipeline** - `21694ac` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `tests/test_nba_context_integration.py` - Two async integration tests: test_context_signals_adjust_probability (ROADMAP SC 5 assertion) and test_none_signals_returns_baseline (regression guard)

## Decisions Made

- Patch target `sportsbet.prop.nba_agents.run_nba_prop_query` (consumer module) not `sportsbet.prop.nba_executor.run_nba_prop_query` (origin) — Phase 8 locked pattern: module-level imports must be patched at the consumer
- `target_date=date(2024, 11, 20)` passed explicitly to the producer so rest_days computation is deterministic regardless of when tests run
- Two separate pool objects (`producer_pool` and `agent_pool`) — keeps the mock setup explicit and prevents accidental cross-contamination between producer and agent DB calls
- `Decimal("0.55")` and `Decimal("0.42")` used for BASE_PROB — PropResult is ConfigDict(strict=True) which rejects raw Python float values

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Both tests passed on first run. Full suite: 201 passed, 11 skipped, 2 xfailed — no regressions (2 new tests added vs previous 199 passed baseline).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ROADMAP Phase 20 is complete: all three plans (01: producer, 02: graph wiring, 03: integration tests) are done
- INT-3 gap is provably closed: NBAContextSignals auto-populates on every nba_prop_analysis run, _apply_nba_context_adjustments fires with real data, and integration tests confirm adjusted != baseline
- Requirements PROP-05 and NBA-02 satisfied across Plans 01, 02, and 03

## Self-Check: PASSED

- FOUND: tests/test_nba_context_integration.py
- FOUND: 21694ac (task commit)
- Both tests pass: python -m pytest tests/test_nba_context_integration.py -x -q -> 2 passed
- Full suite: 201 passed, 11 skipped, 2 xfailed — no regressions

---
*Phase: 20-nba-context-signals-auto-population*
*Completed: 2026-03-26*
