---
phase: 20-nba-context-signals-auto-population
plan: 02
subsystem: api
tags: [langgraph, graph, nba, context-signals, routing, producer]

# Dependency graph
requires:
  - phase: 20-01
    provides: make_nba_context_signals_producer factory and NBAContextSignals Pydantic model

provides:
  - nba_context_producer node registered in LangGraph StateGraph
  - router -> nba_context_producer -> nba_quant_agent -> prop_arbitrage_agent chain
  - create_graph_with_sqlite() wires make_nba_context_signals_producer(pool) when pool provided
  - _nba_context_stub inline fallback (nba_context_signals=None, backward-compat)

affects: [graph, nba_prop_analysis, create_graph_with_sqlite, INT-3]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Inline stub co-located in create_graph() body (follows Phase 6 _kinematic_stub pattern)
    - Lazy import of make_nba_context_signals_producer inside if pool is not None block (Phase 8/14 locked pattern)
    - Router key routing to intermediate producer node before quant node (sequential graph insertion)

key-files:
  created: []
  modified:
    - src/sportsbet/graph/graph.py

key-decisions:
  - "nba_context_producer inserted between router and nba_quant_agent — router 'nba_quant_agent' key maps to 'nba_context_producer' destination; nba_quant_agent node name unchanged"
  - "_nba_context_stub defined inline in create_graph() body — co-located with usage, avoids module namespace pollution, follows Phase 6 _kinematic_stub pattern"
  - "Lazy import of make_nba_context_signals_producer inside if pool is not None block — consistent with Phase 8/14 locked pattern for all pool-gated imports in create_graph_with_sqlite()"

patterns-established:
  - "Intermediate context producer pattern: router key maps to producer node, fixed edge producer->quant ensures context precedes computation"

requirements-completed: [PROP-05, NBA-02]

# Metrics
duration: 4min
completed: 2026-03-26
---

# Phase 20 Plan 02: NBA Context Signals Graph Wiring Summary

**LangGraph topology extended with nba_context_producer node inserted between router and nba_quant_agent, completing INT-3 closure so NBAContextSignals auto-populate on every nba_prop_analysis run**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-26T14:48:41Z
- **Completed:** 2026-03-26T14:52:31Z
- **Tasks:** 1 of 1
- **Files modified:** 1

## Accomplishments

- Added `nba_context_producer_node` parameter to `create_graph()` with inline `_nba_context_stub` fallback returning `{"nba_context_signals": None}` (backward-compatible)
- Redirected router's `"nba_quant_agent"` key to `"nba_context_producer"` node destination, and added fixed edge `nba_context_producer -> nba_quant_agent` for sequential execution
- Wired `make_nba_context_signals_producer(pool)` in `create_graph_with_sqlite()` when pool is provided (lazy import, pool-gated, follows Phase 8/14 locked pattern)
- Updated module-level topology docstring to reflect new four-stage chain

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire nba_context_producer into create_graph() and create_graph_with_sqlite()** - `8e1c5b1` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/sportsbet/graph/graph.py` - Added nba_context_producer_node param, _nba_context_stub inline stub, node registration, routing map update, fixed edge, and create_graph_with_sqlite wiring

## Decisions Made

- Router key `"nba_quant_agent"` maps to `"nba_context_producer"` destination in `add_conditional_edges` — `route_from_master` still returns `"nba_quant_agent"` string unchanged; only the mapping destination changes. This preserves backward-compat for the router function while inserting the producer into the execution chain.
- `_nba_context_stub` defined inline inside `create_graph()` body — follows the Phase 6 `_kinematic_stub` pattern exactly (avoids module namespace pollution, co-located with usage).
- Lazy import `from sportsbet.prop.nba_context_producer import make_nba_context_signals_producer` placed inside `if pool is not None:` block — consistent with Phase 8/14 locked pattern for all pool-gated factory imports in `create_graph_with_sqlite()`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All 199 tests passed on first run. Graph topology check confirmed both `nba_context_producer` and `nba_quant_agent` in compiled node list.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- INT-3 closure complete: every nba_prop_analysis pipeline run now auto-populates NBAContextSignals before nba_quant_agent executes
- The four-stage contextual adjustment (_apply_nba_context_adjustments) fires automatically with real DB-sourced data when pool is provided
- With stub node, existing tests run without regression (nba_context_signals=None means no adjustments applied)
- Phase 20 Plan 03 (integration test) can now verify full pipeline e2e

## Self-Check: PASSED

- `src/sportsbet/graph/graph.py` — FOUND
- `.planning/phases/20-nba-context-signals-auto-population/20-02-SUMMARY.md` — FOUND
- Commit `8e1c5b1` — FOUND

---
*Phase: 20-nba-context-signals-auto-population*
*Completed: 2026-03-26*
