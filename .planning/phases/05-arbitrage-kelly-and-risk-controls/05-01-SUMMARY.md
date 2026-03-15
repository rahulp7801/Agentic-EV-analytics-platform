---
phase: 05-arbitrage-kelly-and-risk-controls
plan: 01
subsystem: api
tags: [arbitrage, kelly-criterion, ev-calculation, pydantic, asyncpg, langgraph]

# Dependency graph
requires:
  - phase: 03-quant-engine
    provides: QuantResult.true_probability — input probability for Kelly sizing
  - phase: 04-context-and-odds-ingestion
    provides: AgentOddsSnapshot.implied_probability — sportsbook probability for EV comparison
  - phase: 02-agent-infrastructure
    provides: EVSignal model with kelly_fraction le 0.25 constraint; GraphState schema

provides:
  - fractional_kelly(p, b, fraction) -> Decimal — bankroll-fraction sizing hard-capped at 0.25
  - compute_ev_percentage(true_prob, implied_prob) -> Decimal — EV edge floored at 0
  - build_trade_plan(ev_pct, kelly_frac, injury_flags, market_type) -> list[str] — 3-bullet thesis
  - make_arbitrage_agent(settings_override) closure — async LangGraph node returning EVSignal or None

affects:
  - 05-02 — risk controls plan reads ev_signal from GraphState set by make_arbitrage_agent
  - 06-kinematic-agent — may need to override true_probability before arbitrage agent runs

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Closure factory pattern: make_arbitrage_agent() mirrors make_quant_agent() and make_context_agent()
    - Decimal-only arithmetic: all Kelly/EV math uses Decimal; float only for display f-string formatting
    - Guard-first agent logic: None checks for quant_result and odds_snapshot before computation
    - EV floor-at-zero: compute_ev_percentage suppresses negative EV before EVSignal construction

key-files:
  created:
    - src/sportsbet/arbitrage/__init__.py
    - src/sportsbet/arbitrage/kelly.py
    - src/sportsbet/arbitrage/ev.py
    - tests/test_arbitrage.py
  modified:
    - src/sportsbet/graph/agents.py
    - tests/test_quant.py

key-decisions:
  - "make_arbitrage_agent takes optional settings_override (not pool) — arbitrage math is stateless; no DB access needed"
  - "compute_ev_percentage = true_prob - implied_prob, floored at 0 — simplest correct edge definition before devig"
  - "build_trade_plan uses float() only for display formatting — all upstream Decimal arithmetic preserved"
  - "asyncio.run() replaces deprecated asyncio.get_event_loop().run_until_complete() in test_quant.py — prevents event loop conflict across test files on Python 3.12"

patterns-established:
  - "Pattern: Guard-first closure nodes — check QuantResult and odds_snapshot None before any math"
  - "Pattern: Decimal(str(cfg.max_kelly_fraction)) for Settings float -> Decimal conversion — same pattern as _extract_odds_snapshot"
  - "Pattern: TDD Red/Green — test file created before implementation, 6/8 tests skipped RED, then 8/8 GREEN"

requirements-completed: [ARBT-01, ARBT-02]

# Metrics
duration: 4min
completed: 2026-03-14
---

# Phase 5 Plan 01: Arbitrage Agent — Kelly/EV Core Summary

**Fractional Kelly arbitrage agent with EV edge computation, 3-bullet trade plan generation, and Decimal-pure sizing hard-capped at 25% of bankroll.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-14T08:56:00Z
- **Completed:** 2026-03-14T09:00:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- `sportsbet.arbitrage` subpackage: `kelly.py` (fractional_kelly) and `ev.py` (compute_ev_percentage, build_trade_plan) with pure Decimal arithmetic throughout
- `make_arbitrage_agent()` closure factory added to `agents.py` — same pattern as make_quant_agent/make_context_agent; sync arbitrage_agent stub preserved for backward-compat
- 8 TDD tests in `test_arbitrage.py` covering Kelly standard, cap, negative-EV, EV positive, EV no-edge, trade plan length, EVSignal production, and kelly_fraction non-flat constraint

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — test scaffold + arbitrage subpackage skeleton** - `37f5fd1` (feat)
2. **Task 2: Real make_arbitrage_agent closure in agents.py** - `ee0b7f7` (feat)

_Note: TDD tasks — tests written first (RED skipped), then implementation (GREEN 8/8)_

## Files Created/Modified

- `src/sportsbet/arbitrage/__init__.py` — subpackage marker
- `src/sportsbet/arbitrage/kelly.py` — fractional_kelly(p, b, fraction) -> Decimal with 0.25 cap and 0 floor
- `src/sportsbet/arbitrage/ev.py` — compute_ev_percentage and build_trade_plan (exactly 3 bullets)
- `tests/test_arbitrage.py` — 8 TDD tests (ARBT-01, ARBT-02 coverage)
- `src/sportsbet/graph/agents.py` — make_arbitrage_agent closure added; module docstring updated
- `tests/test_quant.py` — asyncio.get_event_loop().run_until_complete() → asyncio.run() (Rule 1 auto-fix)

## Decisions Made

- `make_arbitrage_agent` takes `settings_override: Settings | None` (not pool) — arbitrage math is pure computation with no DB access; pool injection unnecessary
- `compute_ev_percentage = true_prob - implied_prob` floored at 0 — simplest correct positive-edge definition; devig applied at ingestion in Phase 4
- `build_trade_plan` uses `float()` only for display string formatting; all upstream arithmetic stays pure Decimal
- `asyncio.run()` replaces deprecated `asyncio.get_event_loop().run_until_complete()` in test_quant.py to prevent event loop conflict on Python 3.12 when tests run together

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed asyncio event loop conflict in test_quant.py**
- **Found during:** Task 2 verification (full suite run)
- **Issue:** `asyncio.get_event_loop().run_until_complete()` in test_quant.py fails with "There is no current event loop" after `asyncio.run()` calls in test_arbitrage.py consume the event loop on Python 3.12/Windows
- **Fix:** Replaced 2 `asyncio.get_event_loop().run_until_complete()` calls with `asyncio.run()` in test_quant.py (lines 136 and 160)
- **Files modified:** `tests/test_quant.py`
- **Verification:** Full suite: 67 passed, 9 skipped, 0 failed
- **Committed in:** `ee0b7f7` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug)
**Impact on plan:** Event loop fix required for test suite health on Python 3.12. No scope creep — test_quant.py already contained the fragility; new asyncio.run() in test_arbitrage.py exposed it.

## Issues Encountered

None beyond the auto-fixed event loop issue above.

## Next Phase Readiness

- Arbitrage math core is complete — `make_arbitrage_agent` produces EVSignal when edge > 0, returns None otherwise
- Phase 5 Plan 02 (risk controls) can read `ev_signal` from GraphState to apply drawdown limits and correlation hard-stops
- Phase 6 Kinematic Agent can set `quant_result.true_probability` before arbitrage agent runs to override base probability

---
*Phase: 05-arbitrage-kelly-and-risk-controls*
*Completed: 2026-03-14*
