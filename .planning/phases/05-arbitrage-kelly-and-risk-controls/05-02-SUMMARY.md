---
phase: 05-arbitrage-kelly-and-risk-controls
plan: 02
subsystem: arbitrage
tags: [correlation-guard, aggregator, drawdown, risk-controls, tdd, pydantic]

# Dependency graph
requires:
  - phase: 05-01
    provides: EVSignal model with market_type field; make_arbitrage_agent closure
  - phase: 02-agent-infrastructure
    provides: EVSignal.kelly_fraction le 0.25 Decimal constraint; GraphState schema

provides:
  - CorrelationGuard.check(signals) -> list[EVSignal] — removes both market_types in a conflict pair
  - CONFLICT_PAIRS frozenset — hardcoded set of conflicting market type pairs
  - Aggregator.record_signal(signal) -> bool — daily drawdown gate returning True/False
  - Aggregator.cumulative_exposure_usd — tracks total accepted exposure in USD

affects:
  - 05-03 — graph wiring plan will wire CorrelationGuard and Aggregator into LangGraph nodes

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure-class risk controls: CorrelationGuard and Aggregator have no LangGraph coupling — testable in isolation"
    - "frozenset[frozenset[str]] for CONFLICT_PAIRS: immutable, hashable, O(1) membership test for set-intersection check"
    - "Decimal(str(float)) conversion in Aggregator.__init__: same pattern as config.py Settings float -> Decimal"
    - "Gate-closes-on-trigger semantics: Aggregator gate stays closed once limit reached; triggering signal is NOT added to cumulative"
    - "TDD Red/Green: tests written first (8 skipped RED), then implementation (16/16 GREEN)"

key-files:
  created:
    - src/sportsbet/arbitrage/correlation_guard.py
    - src/sportsbet/arbitrage/aggregator.py
  modified:
    - tests/test_arbitrage.py

key-decisions:
  - "CONFLICT_PAIRS hardcoded at module level: frozenset of frozenset — immutable, O(1) membership test, extensible without touching class logic"
  - "Aggregator gate-on-limit semantics: triggering signal is blocked and NOT counted in cumulative_exposure_usd — conservative prop-firm interpretation of daily drawdown limit"
  - "Gate stays closed after triggering: consistent with prop firm daily hard stop — no partial recovery within same instance lifetime"
  - "No LangGraph coupling in Plan 02: both classes are pure Python; graph wiring is deferred to Plan 03"

# Metrics
duration: 2min
completed: 2026-03-15
---

# Phase 5 Plan 02: CorrelationGuard and Aggregator Risk Controls Summary

**CorrelationGuard blocks conflicting market pairs (over/under same stat) and Aggregator enforces daily drawdown gate with gate-closes-on-limit semantics — both pure Python, no LangGraph coupling.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-15T04:22:58Z
- **Completed:** 2026-03-15T04:25:57Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `CorrelationGuard` in `correlation_guard.py`: stateless class with `CONFLICT_PAIRS` frozenset (4 pairs) and `check()` method — O(n * |CONFLICT_PAIRS|) set-intersection removes both members of any detected conflict pair
- `Aggregator` in `aggregator.py`: stateful daily drawdown gate — `record_signal()` returns True/False, gate triggers when cumulative + new exposure >= limit, stays closed for instance lifetime
- 8 new TDD tests added to `test_arbitrage.py` (4 ARBT-03, 4 ARBT-04); full suite 75 passed, 9 skipped, 0 failures

## Task Commits

Each task was committed atomically using TDD Red/Green:

1. **TDD RED: ARBT-03 and ARBT-04 failing tests** - `2288a91` (test)
2. **Task 1 GREEN: CorrelationGuard implementation** - `f97d34d` (feat)
3. **Task 2 GREEN: Aggregator implementation** - `572879a` (feat)

## Files Created/Modified

- `src/sportsbet/arbitrage/correlation_guard.py` — CorrelationGuard class with CONFLICT_PAIRS; exports CorrelationGuard and CONFLICT_PAIRS
- `src/sportsbet/arbitrage/aggregator.py` — Aggregator class with bankroll_usd, daily_drawdown_limit, record_signal(), cumulative_exposure_usd, gate_triggered
- `tests/test_arbitrage.py` — expanded with _make_signal() factory and 8 new ARBT-03/ARBT-04 tests

## Decisions Made

- `CONFLICT_PAIRS` hardcoded at module level as `frozenset[frozenset[str]]`: immutable and hashable, O(1) `in` test per pair, extensible by adding entries without touching CorrelationGuard class logic
- Aggregator gate-on-limit semantics: triggering signal is blocked and NOT added to `cumulative_exposure_usd` — conservative interpretation matching prop firm hard stop (you don't get to spend right up to the limit)
- Gate stays permanently closed after triggering for the instance's lifetime; no partial recovery — resets only on process restart (new instance)
- No LangGraph coupling in Plan 02 per plan spec — graph wiring deferred to Plan 03

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- CorrelationGuard and Aggregator are fully tested standalone modules ready for LangGraph wiring in Plan 03
- Plan 03 graph wiring will inject CorrelationGuard.check() and Aggregator.record_signal() as post-processing steps after make_arbitrage_agent produces EVSignal
- CONFLICT_PAIRS can be extended with additional market type pairs without modifying CorrelationGuard logic

## Self-Check

- `src/sportsbet/arbitrage/correlation_guard.py` — exists, 46 lines
- `src/sportsbet/arbitrage/aggregator.py` — exists, 79 lines
- Commit `2288a91` (RED tests), `f97d34d` (CorrelationGuard GREEN), `572879a` (Aggregator GREEN) — all verified in git log

---
*Phase: 05-arbitrage-kelly-and-risk-controls*
*Completed: 2026-03-15*
