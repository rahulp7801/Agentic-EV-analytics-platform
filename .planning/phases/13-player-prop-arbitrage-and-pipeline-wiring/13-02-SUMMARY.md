---
phase: 13-player-prop-arbitrage-and-pipeline-wiring
plan: "02"
subsystem: graph
tags: [langgraph, graph-wiring, prop-pipeline, routing, integration-tests]

# Dependency graph
requires:
  - phase: 13-01
    provides: "make_prop_arbitrage_agent closure factory, EVSignal for prop markets, extended CONFLICT_PAIRS"
  - phase: 12
    provides: "make_nba_quant_agent closure, nba_prop_result PropResult, NBAContextSignals"
  - phase: 11
    provides: "make_prop_quant_agent closure, prop_result PropResult, GraphState prop_type/prop_line fields"
  - phase: 5
    provides: "make_correlation_guard_node, make_aggregator_node, arbitrage risk controls"
provides:
  - "Extended create_graph() with prop_quant_node, nba_quant_node, prop_arbitrage_node params"
  - "route_from_master handles nba_prop_analysis -> nba_quant_agent and prop_arbitrage_analysis -> prop_arbitrage_agent"
  - "Chained prop pipeline: prop_quant_agent -> prop_arbitrage_agent -> correlation_guard -> aggregator -> END"
  - "Chained NBA prop pipeline: nba_quant_agent -> prop_arbitrage_agent -> correlation_guard -> aggregator -> END"
  - "Direct prop_arbitrage_analysis route: master_router -> prop_arbitrage_agent -> correlation_guard -> aggregator -> END"
  - "create_graph_with_sqlite() wires make_prop_quant_agent, make_nba_quant_agent, make_prop_arbitrage_agent when pool provided"
  - "7-test integration suite covering router extension, graph compilation, and e2e pipelines"
affects:
  - future-frontend
  - phase-14-if-any

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Multi-predecessor node pattern: LangGraph supports prop_quant_agent and nba_quant_agent both chaining to same prop_arbitrage_agent"
    - "Shared downstream risk pipeline: prop_arbitrage_agent reuses same correlation_guard->aggregator chain as arbitrage_agent"
    - "Inline stub co-location: _prop_quant_stub, _nba_quant_stub, _prop_arb_stub defined inside create_graph() body (matches _kinematic_stub pattern)"
    - "Pool-gated factory wiring: prop nodes wired in create_graph_with_sqlite() only when pool is not None"

key-files:
  created:
    - tests/test_prop_pipeline_wiring.py
  modified:
    - src/sportsbet/graph/router.py
    - src/sportsbet/graph/graph.py

key-decisions:
  - "Aggregator bankroll in e2e tests set to 100_000 USD (not 10_000) so Kelly fraction (6% * bankroll) stays under 10% daily drawdown limit — test isolation concern, not production config"
  - "prop_arbitrage_agent reuses correlation_guard->aggregator chain from arbitrage pipeline — no new nodes registered; add_edge from prop_arbitrage_agent to correlation_guard when guard is present"
  - "Two prop quant agents (NFL and NBA) chain to same prop_arbitrage_agent via separate add_edge() calls — LangGraph supports multiple predecessors to same node"
  - "create_graph_with_sqlite() wires make_prop_arbitrage_agent(sport='nfl') only — NBA sport param not exposed at factory level; sport selection is per-graph-construction, not per-request"

patterns-established:
  - "Routing dict keys must match route_from_master return values exactly — RESEARCH.md Pitfall 3; 'prop_quant_agent' key added alongside node registration"
  - "TDD bankroll sizing: use large bankroll (100_000) with high drawdown limit (0.10) in unit tests to prevent Aggregator gate from interfering with pipeline wiring tests"

requirements-completed:
  - PROP-06
  - PROP-07

# Metrics
duration: 5min
completed: 2026-03-23
---

# Phase 13 Plan 02: Prop Pipeline Wiring Summary

**LangGraph graph wired for end-to-end NFL and NBA prop pipelines: prop_quant_agent and nba_quant_agent chain to shared prop_arbitrage_agent -> correlation_guard -> aggregator in a single ainvoke**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-23T20:35:20Z
- **Completed:** 2026-03-23T20:40:29Z
- **Tasks:** 2 (TDD: RED + GREEN each)
- **Files modified:** 3

## Accomplishments

- Extended router.py with nba_prop_analysis and prop_arbitrage_analysis routes (2 new elif branches)
- Extended create_graph() with three new optional params (prop_quant_node, nba_quant_node, prop_arbitrage_node), inline stubs, and conditional edges routing dict entries
- Wired chained prop pipeline topology: both prop quant agents drain to shared prop_arbitrage_agent which reuses the existing correlation_guard->aggregator chain
- Extended create_graph_with_sqlite() to wire all three prop nodes when pool is available (Phase 13 production factory closure)
- 7-test integration suite confirms router extension, graph compilation, and end-to-end pipeline for NFL/NBA props and direct prop_arbitrage_analysis route
- Full suite: 153 passed, 0 failures (no regressions across all prior phases)

## Task Commits

1. **Task 1 (RED): Write failing integration tests** - `748b958` (test)
2. **Task 2 (GREEN): Extend router.py and graph.py** - `8a9b229` (feat)

## Files Created/Modified

- `tests/test_prop_pipeline_wiring.py` - 7 integration tests for prop pipeline wiring (router, graph compilation, e2e NFL, e2e NBA, direct route)
- `src/sportsbet/graph/router.py` - Added nba_prop_analysis and prop_arbitrage_analysis routes; updated module docstring
- `src/sportsbet/graph/graph.py` - Three new params in create_graph(), inline stubs, node registrations, conditional edges extension, chaining edges, create_graph_with_sqlite() wiring

## Decisions Made

- **Aggregator bankroll in tests:** Set to 100,000 USD (not 10,000) so Kelly fraction (6% * bankroll = 6,000) stays under 10% drawdown limit (10,000). Tests are about pipeline wiring, not bankroll sizing — large bankroll prevents the Aggregator gate from interfering with wiring assertions.
- **Shared correlation_guard->aggregator chain:** prop_arbitrage_agent reuses the same guard/aggregator nodes as arbitrage_agent via `add_edge("prop_arbitrage_agent", "correlation_guard")`. No new risk nodes registered — LangGraph multiple-predecessor topology is correct.
- **create_graph_with_sqlite() wires sport="nfl" only:** The sport param selects which state key the arbitrage agent reads; single factory wires NFL variant. Production callers requiring NBA-specific arbitrage can pass a custom prop_arbitrage_node to create_graph().

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Aggregator bankroll too small for e2e tests**
- **Found during:** Task 2 GREEN phase (first test run)
- **Issue:** Initial bankroll 10,000 USD with 5% limit gives 500 USD max daily exposure. Kelly fraction 6% of 10,000 = 600 USD exceeds the 500 USD limit, so Aggregator blocked the signal — ev_signal was None despite correct pipeline execution.
- **Fix:** Changed e2e test bankroll to 100,000 USD with 10% drawdown limit (10,000 USD limit > 6,000 USD Kelly stake). Tests are wiring tests, not risk-sizing tests.
- **Files modified:** tests/test_prop_pipeline_wiring.py
- **Verification:** All 17 tests pass; ev_signal non-None in all three e2e tests
- **Committed in:** 8a9b229 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in test bankroll sizing)
**Impact on plan:** Fix required for correct test behavior — pipeline wiring was correct, test fixture was misconfigured.

## Issues Encountered

None beyond the bankroll sizing deviation documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 13 complete: all prop pipeline components wired end-to-end (PROP-06 + PROP-07)
- Production entry point create_graph_with_sqlite() wires NFL prop pipeline when pool provided
- NBA sport selection at graph construction level deferred to future phase if NBA-specific routing required
- Full suite green: 153 passed, ready for v1.0 milestone review

---
*Phase: 13-player-prop-arbitrage-and-pipeline-wiring*
*Completed: 2026-03-23*
