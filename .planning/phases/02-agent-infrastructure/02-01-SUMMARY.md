---
phase: 02-agent-infrastructure
plan: "01"
subsystem: infra
tags: [pydantic, pydantic-v2, models, graph, tdd, typing, decimal, kelly-criterion]

# Dependency graph
requires:
  - phase: 01-data-foundation
    provides: "OddsSnapshotCreate Pydantic v2 pattern (ConfigDict strict=True, field_validator)"
provides:
  - "QuantParams: typed SQL query input for Quant Agent with Literal stat_type and season range guard"
  - "QuantResult: stub output model for Quant Agent — all fields nullable for Phase 3 population"
  - "EVSignal: +EV flag output with kelly_fraction cap (0,0.25], ev_percentage > 0, trade_plan max 3 bullets"
  - "AgentOddsSnapshot: odds snapshot with Decimal implied_probability (never raw American odds int)"
  - "GameState: shared game context matching GraphState shape with nullable weather_json"
  - "src/sportsbet/graph package: package marker for Phase 2 graph wiring"
affects:
  - 02-agent-infrastructure
  - 03-quant-agent
  - 04-arbitrage-agent
  - 05-context-agent

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pydantic v2 ConfigDict(strict=True) on all agent I/O models — no v1 class Config"
    - "Annotated + Field constraints for range guards (ge/le/gt/max_length) — no custom validators where avoidable"
    - "Decimal (not float) for all probability and fraction values — precision through Kelly pipeline"
    - "Literal type for stat_type to prevent open-ended string injection into SQL query builder"
    - "Optional[X] = None for nullable stub fields — Phase 3 populates real values"
    - "TDD cycle: RED commit before implementation, GREEN commit after all 10 tests pass"

key-files:
  created:
    - src/sportsbet/graph/__init__.py
    - src/sportsbet/graph/models.py
    - tests/test_models.py
  modified: []

key-decisions:
  - "Annotated + Field constraints (ge/le/gt/max_length) preferred over @field_validator for simple range guards — less boilerplate, same enforcement"
  - "QuantResult stub with all-nullable fields allows Phase 2 stub nodes to return QuantResult() without DB access"
  - "AgentOddsSnapshot stores Decimal implied_probability not raw American odds int — conversion happens at ingestion time to prevent unit-mismatch bugs in agent layer"
  - "EVSignal.kelly_fraction hard cap at 0.25 (fractional Kelly) enforced at model level — not just convention"

patterns-established:
  - "Agent I/O model pattern: ConfigDict(strict=True) + Annotated Field constraints + Decimal for probabilities"
  - "Stub model pattern: all nullable fields with None defaults — Phase 3 replaces with real computed values"

requirements-completed:
  - INFRA-03

# Metrics
duration: 3min
completed: 2026-03-11
---

# Phase 2 Plan 01: Pydantic v2 Agent I/O Models Summary

**Five Pydantic v2 strict models (QuantParams, QuantResult, EVSignal, AgentOddsSnapshot, GameState) providing typed contracts for all downstream agents, with Kelly Criterion hard-caps enforced at validation time**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-11T00:43:06Z
- **Completed:** 2026-03-11T00:45:20Z
- **Tasks:** 2 (RED + GREEN TDD cycle)
- **Files modified:** 3 created, 0 modified

## Accomplishments

- Implemented 5 Pydantic v2 strict models with zero v1 patterns — all use ConfigDict(strict=True) and Annotated Field constraints
- Enforced mathematical hard-stops at the type layer: kelly_fraction in (0, 0.25], ev_percentage > 0, trade_plan max 3 items, season in [1999, 2030]
- AgentOddsSnapshot stores Decimal implied_probability exclusively — raw American odds integers are rejected by strict=True validation
- Full TDD cycle: 10 RED tests committed before implementation, 10 GREEN tests passing after

## Task Commits

Each task was committed atomically:

1. **Task 1: TDD RED — failing tests** - `c21dae7` (test)
2. **Task 2: TDD GREEN — model implementation** - `bef10f3` (feat)

_Note: TDD plan — RED commit before implementation, GREEN commit after all tests pass._

## Files Created/Modified

- `src/sportsbet/graph/__init__.py` - Graph package marker for sportsbet.graph import path
- `src/sportsbet/graph/models.py` - 5 Pydantic v2 agent I/O models with full constraint enforcement
- `tests/test_models.py` - 10 tests: happy paths + rejection cases for all 5 models

## Decisions Made

- Used `Annotated + Field(ge=..., le=..., gt=..., max_length=...)` for range guards instead of `@field_validator` — less boilerplate, same enforcement, cleaner model code
- `QuantResult` has all-nullable fields with `None` defaults so Phase 2 stub nodes can instantiate `QuantResult()` without touching the database
- `AgentOddsSnapshot.implied_probability` is `Decimal` not `int` — the conversion from raw American odds to implied probability happens at ingestion time; agents never see raw odds integers to prevent unit-mismatch bugs
- `EVSignal.kelly_fraction` cap at `Decimal("0.25")` is enforced at model construction — not just a documented convention — matching CLAUDE.md prop firm rule for fractional Kelly

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 5 typed contracts are ready for Phase 2 Plan 02 (graph wiring stub nodes)
- Phase 3+ agents can code against QuantParams, EVSignal, AgentOddsSnapshot, GameState, QuantResult immediately
- QuantResult stub design allows Plan 02 nodes to return fixture instances — Phase 3 replaces with real SQL query results

---
*Phase: 02-agent-infrastructure*
*Completed: 2026-03-11*

## Self-Check: PASSED

- src/sportsbet/graph/__init__.py: FOUND
- src/sportsbet/graph/models.py: FOUND
- tests/test_models.py: FOUND
- .planning/phases/02-agent-infrastructure/02-01-SUMMARY.md: FOUND
- commit c21dae7 (test RED): FOUND
- commit bef10f3 (feat GREEN): FOUND
