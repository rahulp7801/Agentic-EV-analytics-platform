---
phase: 02-agent-infrastructure
plan: "02"
subsystem: infra

tags: [langgraph, pydantic, stategraph, typeddict, annotated-reducers, stub-agents]

requires:
  - phase: 02-agent-infrastructure
    plan: "01"
    provides: "QuantResult, EVSignal, GameState Pydantic v2 models in sportsbet.graph.models"
  - phase: 01-data-foundation
    provides: "asyncpg pool, PostgreSQL schema, src layout with pythonpath=['src','site-packages']"

provides:
  - "GraphState TypedDict with 13 fields and Annotated last-write-wins reducer on error field"
  - "master_router passthrough node + route_from_master conditional edge function"
  - "quant_agent stub returning QuantResult fixture (true_probability=0.62, sample_size=142)"
  - "arbitrage_agent stub returning EVSignal fixture (ev_percentage=0.07, kelly_fraction=0.05)"
  - "context_agent stub passthrough returning empty dict"
  - "create_graph() factory returning CompiledStateGraph — exported from sportsbet.graph"
  - "9-test suite for GraphState reducers and full graph routing"

affects:
  - 02-03-checkpointer
  - 03-quant-agent
  - 04-context-agent
  - 05-arbitrage-agent

tech-stack:
  added:
    - "langgraph>=1.1.0 (installed to site-packages; StateGraph, END, CompiledStateGraph)"
  patterns:
    - "Stub agents return partial dict (not full GraphState) — LangGraph merges into state via reducers"
    - "Annotated[str | None, reducer_fn] on error field for LangGraph INFRA-01 compliance"
    - "route_from_master reads error first (fail-fast) then dispatches by request_type"
    - "create_graph() factory pattern — downstream phases call this and replace stubs"

key-files:
  created:
    - src/sportsbet/graph/state.py
    - src/sportsbet/graph/router.py
    - src/sportsbet/graph/agents.py
    - src/sportsbet/graph/graph.py
    - tests/test_graph.py
  modified:
    - src/sportsbet/graph/__init__.py

key-decisions:
  - "Stub agents return partial dicts (not full GraphState) — LangGraph merges dict into state using Annotated reducers; returning full TypedDict would require all 13 fields in every agent"
  - "route_from_master (conditional edge fn) handles routing logic, master_router node is pure passthrough — separation of concerns matches LangGraph's intended API"
  - "GraphState.error uses _last_write_wins reducer (b wins) for LangGraph INFRA-01 compliance — only one agent runs per request cycle so no true concurrent conflict, but Annotated required"
  - "No checkpointer attached in Plan 02-02 — Plan 02-03 adds AsyncPostgresSaver after graph skeleton is validated"
  - "langgraph installed to site-packages/ directory (existing Windows pip --target workaround) not added to pyproject.toml dependencies — matches Phase 1 decision pattern"

patterns-established:
  - "Pattern: Stub agents store fixture Pydantic instances on GraphState so Phase 3/5 develop against real interface contracts, not placeholder dicts"
  - "Pattern: entry-point -> router -> conditional_edges -> specialist -> END topology locked for all future phases"
  - "Pattern: test_graph.py uses make_minimal_state() helper returning valid 13-field dict for all routing tests"

requirements-completed:
  - INFRA-01
  - INFRA-02

duration: 20min
completed: 2026-03-11
---

# Phase 2 Plan 02: LangGraph Graph Skeleton Summary

**LangGraph StateGraph skeleton with GraphState TypedDict (13 fields, Annotated reducer), Master Router dispatching to 3 stub agents (quant/arbitrage/context), fixture Pydantic instances on state, 9 tests green**

## Performance

- **Duration:** 20 min
- **Started:** 2026-03-11T00:49:24Z
- **Completed:** 2026-03-11T01:09:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- GraphState TypedDict with all 13 required fields; `error` field uses `Annotated[str | None, _last_write_wins]` reducer for LangGraph INFRA-01 compliance
- Master Router with conditional edge dispatch: pre-set error routes to END immediately; request_type dispatches to quant_agent, arbitrage_agent, or context_agent
- Stub agents return hardcoded Pydantic fixture instances (QuantResult, EVSignal) stored on GraphState — Phase 3 and Phase 5 can develop against real interface contracts immediately
- `create_graph()` factory exported from `sportsbet.graph` compiles and ainvokes without exception; full suite: 26 passed, 7 skipped

## Task Commits

Each task was committed atomically:

1. **Task 1: GraphState TypedDict and test stubs** - `b7615dd` (feat)
2. **Task 2: Master Router, stub agents, and compiled StateGraph** - `bf55c6c` (feat)

**Plan metadata:** (docs commit — see below)

_Note: TDD tasks — test file written first (RED), then implementation (GREEN), committed together per task_

## Files Created/Modified

- `src/sportsbet/graph/state.py` - GraphState TypedDict with 13 fields; _last_write_wins reducer on error
- `src/sportsbet/graph/router.py` - master_router passthrough node + route_from_master conditional edge fn
- `src/sportsbet/graph/agents.py` - quant_agent, arbitrage_agent, context_agent stubs with fixture Pydantic instances
- `src/sportsbet/graph/graph.py` - create_graph() factory building and compiling the StateGraph
- `src/sportsbet/graph/__init__.py` - exports create_graph for downstream imports
- `tests/test_graph.py` - 9 tests: 3 GraphState reducer/field tests + 6 routing/invocation tests

## Decisions Made

- Stub agents return partial dicts (not full GraphState) — LangGraph merges dict into state via reducers; this is the correct LangGraph pattern for partial state updates
- `route_from_master` (conditional edge function) handles routing logic, `master_router` node is pure passthrough — matches LangGraph's intended API separation of concerns
- No checkpointer attached in this plan — Plan 02-03 adds AsyncPostgresSaver after graph skeleton validated
- LangGraph 1.1.0 installed to existing `site-packages/` directory (Windows pip --target workaround from Phase 1)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None — LangGraph 1.1.0 was already installed in `site-packages/` from a prior session. The `pythonpath = ['src', 'site-packages']` pytest config made it immediately importable.

## Next Phase Readiness

- `create_graph()` is the stable entry point all downstream phases use — ready for Plan 02-03 (checkpointer)
- Phase 3 (Quant Agent): replace `quant_agent` stub with QuantParams validation + asyncpg SQL query; QuantResult fixture instance on GraphState provides real interface contract to code against
- Phase 5 (Arbitrage Agent): replace `arbitrage_agent` stub with real odds comparison; EVSignal fixture instance provides real interface contract
- Phase 4 (Context Agent): replace `context_agent` stub with context stream processing
- Blocker carried forward: verify current LangGraph AsyncPostgresSaver import path before Plan 02-03 coding

---
*Phase: 02-agent-infrastructure*
*Completed: 2026-03-11*
