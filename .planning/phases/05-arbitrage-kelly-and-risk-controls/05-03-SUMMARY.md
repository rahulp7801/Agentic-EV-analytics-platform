---
phase: 05-arbitrage-kelly-and-risk-controls
plan: 03
subsystem: api
tags: [langgraph, arbitrage, kelly, correlation-guard, aggregator, ev-signal, risk-controls]

# Dependency graph
requires:
  - phase: 05-01
    provides: make_arbitrage_agent closure factory, EVSignal model, kelly/ev math
  - phase: 05-02
    provides: CorrelationGuard.check(), Aggregator.record_signal(), drawdown gate
provides:
  - create_graph() extended with arbitrage_node, correlation_guard_node, aggregator_node params
  - make_correlation_guard_node() and make_aggregator_node() graph-layer node factories in graph.py
  - pending_signals and cleared_signals fields on GraphState
  - arbitrage_analysis request_type routes to arbitrage_agent in route_from_master
  - Full pipeline topology: arbitrage_agent -> correlation_guard -> aggregator -> END
  - 4 end-to-end integration tests covering all ARBT-01 through ARBT-04 success criteria
affects:
  - phase-06-kinematic-agent
  - frontend-terminal

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Graph-layer node factory pattern: make_*_node() returns a closure capturing stateful objects (CorrelationGuard, Aggregator)
    - Backward-compat optional node injection: new node params default to None, falling back to Phase 2 stubs
    - Pre-populated state integration test pattern: quant_result + context_signals injected in initial state to drive arbitrage pipeline without full quant/context agents

key-files:
  created: []
  modified:
    - src/sportsbet/graph/state.py
    - src/sportsbet/graph/graph.py
    - src/sportsbet/graph/router.py
    - src/sportsbet/graph/agents.py
    - tests/test_arbitrage.py

key-decisions:
  - "make_correlation_guard_node and make_aggregator_node live in graph.py (not agents.py) — graph-layer orchestration, not agent logic"
  - "Aggregator instance created once at graph construction time — persists cumulative_exposure_usd across ainvoke calls within same process lifetime, simulating daily gate"
  - "arbitrage_analysis request_type added alongside odds_check — both route to arbitrage_agent; cleaner semantic for Phase 5 direct pipeline invocation"
  - "pending_signals written by make_arbitrage_agent (not just aggregator_node) — allows correlation_guard_node to receive the list even before aggregator runs"
  - "Integration tests use pre-populated initial state (quant_result + context_signals injected) rather than full quant/context pipeline — v1 simplicity, avoids sequential routing complexity"
  - "bankroll=100000, daily_drawdown_limit=0.20 in test_e2e_pipeline — ensures kelly_frac ~0.075 passes the gate ($7500 < 20% of $100000 = $20000)"

patterns-established:
  - "Node factory separation: make_*_node() in graph.py vs make_*_agent() in agents.py — agents are stateless pure computations; nodes wrap stateful risk controls"
  - "Conditional pipeline extension: if both guard and aggregator provided -> extended chain; else backward-compat direct-to-END"
  - "E2E integration test pattern: asyncio.run(graph.ainvoke(state, config)) with MemorySaver checkpointer and uuid thread_id"

requirements-completed: [ARBT-01, ARBT-02, ARBT-03, ARBT-04]

# Metrics
duration: 15min
completed: 2026-03-14
---

# Phase 5 Plan 03: Arbitrage Graph Wiring Summary

**LangGraph graph extended with CorrelationGuard and Aggregator as wired nodes, closing the full arbitrage -> risk-controls pipeline with 4 passing end-to-end integration tests**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-14T21:15:00Z
- **Completed:** 2026-03-14T21:30:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Extended `create_graph()` with `arbitrage_node`, `correlation_guard_node`, and `aggregator_node` parameters — backward-compat when omitted (Phase 2 stubs used)
- Added `make_correlation_guard_node()` and `make_aggregator_node()` graph-layer node factories; `arbitrage_agent -> correlation_guard -> aggregator -> END` wired with sequential edges when both risk nodes are provided
- Added `pending_signals` and `cleared_signals` fields to `GraphState`; `make_arbitrage_agent` now writes `pending_signals=[signal]` alongside `ev_signal`
- Added `arbitrage_analysis` request_type to `route_from_master`, routing to `arbitrage_agent` for direct pipeline invocation
- 4 integration tests cover all ROADMAP Phase 5 success criteria: positive EV passes, negative EV suppressed, drawdown gate blocks on tiny limit, correlation conflict pair blocked by guard

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend GraphState and wire CorrelationGuard + Aggregator as LangGraph nodes** - `9d41dc7` (feat)
2. **Task 2: End-to-end integration test — full mock pipeline green** - `7a5d39c` (test)

## Files Created/Modified

- `src/sportsbet/graph/state.py` - Added `pending_signals: list[Any]` and `cleared_signals: list[Any]` fields to GraphState TypedDict
- `src/sportsbet/graph/graph.py` - Added `make_correlation_guard_node()`, `make_aggregator_node()`, extended `create_graph()` with three new node params
- `src/sportsbet/graph/router.py` - Added `arbitrage_analysis` route to `route_from_master`; updated docstring routing table
- `src/sportsbet/graph/agents.py` - `make_arbitrage_agent` now returns `pending_signals=[signal]` alongside `ev_signal` for CorrelationGuard consumption
- `tests/test_arbitrage.py` - Added 4 integration tests: `test_e2e_pipeline`, `test_e2e_pipeline_negative_ev`, `test_e2e_pipeline_drawdown_gate`, `test_e2e_correlation_guard_blocks`

## Decisions Made

- `make_correlation_guard_node` and `make_aggregator_node` placed in `graph.py` (not `agents.py`) — they are graph-layer orchestration wrapping stateful risk objects, not agent logic
- `Aggregator` instance created at graph construction time, persisting cumulative exposure across invocations within the same process — models the daily gate correctly
- Integration tests use pre-populated initial state rather than full Context -> Quant -> Arbitrage chain — v1 simplicity; true sequential chaining deferred to Phase 6
- `bankroll=100000` and `daily_drawdown_limit=0.20` used in `test_e2e_pipeline` to ensure kelly_fraction ~0.075 passes the gate (exposure $7500 < limit $20000)

## Deviations from Plan

None - plan executed exactly as written. The `route_from_quant` complexity mentioned in Task 1 notes was correctly identified as unnecessary (Task 2 clarified to use `arbitrage_analysis` dispatch instead) — this is the plan's own recommended simplification, not a deviation.

## Issues Encountered

- First run of `test_e2e_pipeline` failed because `make_arbitrage_agent` with `max_kelly_fraction=0.25` produces kelly_frac ~0.075, giving $750 exposure against a $500 limit (5% of $10000). Fixed by adjusting test bankroll/limit to `bankroll_usd=100000.0, daily_drawdown_limit=0.20` — no code changes required.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Full arbitrage risk-controls pipeline is wired and tested: ARBT-01 through ARBT-04 complete
- Phase 5 is functionally complete: Kelly sizing, EV computation, CorrelationGuard, Aggregator drawdown gate, and LangGraph integration all green
- Phase 6 (Kinematic Agent) can begin: graph.py wiring patterns established; add kinematic_node parameter following the same optional-injection pattern

## Self-Check: PASSED

- FOUND: src/sportsbet/graph/state.py
- FOUND: src/sportsbet/graph/graph.py
- FOUND: src/sportsbet/graph/router.py
- FOUND: src/sportsbet/graph/agents.py
- FOUND: tests/test_arbitrage.py
- FOUND commit: 9d41dc7 (Task 1 - feat)
- FOUND commit: 7a5d39c (Task 2 - test)

---
*Phase: 05-arbitrage-kelly-and-risk-controls*
*Completed: 2026-03-14*
