---
phase: 11-nfl-player-prop-quant-engine
plan: 02
subsystem: api
tags: [pydantic, langgraph, kinematic, ngs, prop-betting, nfl]

# Dependency graph
requires:
  - phase: 11-01
    provides: PropQueryBuilder, run_prop_query executor, make_prop_quant_agent closure stub
  - phase: 06-kinematic-agent
    provides: KinematicAnalysis model with geometric_mismatch_flag, make_kinematic_agent closure

provides:
  - _apply_kinematic_adjustment full implementation with KINEMATIC_BOOST=0.05, clamped to [0.01, 0.99]
  - KINEMATIC_BOOST and RECEIVING_PROPS constants in sportsbet.prop.agents
  - GraphState.prop_result: Optional[PropResult] field (Phase 11 extension)
  - route_from_master dispatches "prop_analysis" -> "prop_quant_agent"
  - make_prop_quant_agent reads kinematic_result from GraphState (real integration, not None stub)

affects:
  - Any phase constructing or extending GraphState
  - Any phase testing route_from_master routing table
  - Phase 12+ that builds on prop_result signal in graph

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Additive bounded boost: KINEMATIC_BOOST applied only to RECEIVING_PROPS, clamped [0.01, 0.99] using Decimal arithmetic"
    - "Runtime KinematicAnalysis import in agents.py (not TYPE_CHECKING) — LangGraph get_type_hints() compatibility"
    - "GraphState extension pattern: add Optional field + runtime import in state.py, matching Phase 4/6 pattern"
    - "Router extension: add elif branch before else catch-all, update module docstring routing table comment"

key-files:
  created: []
  modified:
    - src/sportsbet/prop/agents.py
    - src/sportsbet/graph/state.py
    - src/sportsbet/graph/router.py
    - tests/test_prop_executor.py

key-decisions:
  - "KinematicAnalysis import moved from TYPE_CHECKING guard to runtime in agents.py — consistent with Phase 4/6 pattern for LangGraph get_type_hints() compatibility"
  - "RECEIVING_PROPS frozenset covers rec_yds, rec_tds, receptions — pass-side props (pass_yds, pass_tds) never adjusted by kinematic separation signal"
  - "Decimal clamping via max(0.01, min(0.99, adjusted)) prevents probability leaking outside valid domain when boost pushes near boundary"
  - "press_man_rate never read in _apply_kinematic_adjustment — always None per Phase 6 schema decision; only geometric_mismatch_flag and true_probability consumed"

patterns-established:
  - "Kinematic signal feedback loop: kinematic_result in GraphState -> _apply_kinematic_adjustment -> boosted PropResult.true_probability"
  - "Conditional kinematic adjustment: four early-return guards (None, prop_type, true_probability, flag) keep function pure and testable in isolation"

requirements-completed: [PROP-04]

# Metrics
duration: 4min
completed: 2026-03-23
---

# Phase 11 Plan 02: NFL Player Prop Quant Engine — Kinematic Integration Summary

**Kinematic separation signal wired into prop probability estimation: receiving props boosted by 0.05 when geometric_mismatch_flag=True, clamped to [0.01, 0.99], with GraphState extended and router updated for end-to-end prop_analysis dispatch.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-23T01:48:02Z
- **Completed:** 2026-03-23T01:52:08Z
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 4

## Accomplishments

- Implemented `_apply_kinematic_adjustment` with additive KINEMATIC_BOOST (0.05) applied only to receiving props (rec_yds, rec_tds, receptions) when `geometric_mismatch_flag=True`, with output clamped to [0.01, 0.99]
- Extended GraphState with `prop_result: Optional[PropResult]` field and added PropResult to runtime imports in state.py
- Added `prop_analysis` -> `prop_quant_agent` routing branch to `route_from_master`
- Wired `make_prop_quant_agent` to read `state["kinematic_result"]` and pass real KinematicAnalysis to adjustment function (replacing None stub from Plan 01)
- All 4 PROP-04 tests green; full test suite 115 passed, 11 skipped, 0 failures

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — un-xfail PROP-04 test stubs and confirm RED** - `96c2e96` (test)
2. **Task 2: GREEN — implement _apply_kinematic_adjustment, extend GraphState and router** - `21a7a77` (feat)

_Note: TDD tasks have separate RED (test) and GREEN (feat) commits per TDD protocol._

## Files Created/Modified

- `tests/test_prop_executor.py` — Removed xfail from 3 existing PROP-04 tests, filled in full assertion bodies, added 4th test (test_kinematic_none_returns_unchanged), imported _apply_kinematic_adjustment and KinematicAnalysis
- `src/sportsbet/prop/agents.py` — Added KINEMATIC_BOOST/RECEIVING_PROPS constants, implemented full _apply_kinematic_adjustment, moved KinematicAnalysis import from TYPE_CHECKING to runtime, wired kinematic_result from state
- `src/sportsbet/graph/state.py` — Added PropResult to runtime import, added prop_result: Optional[PropResult] as final GraphState field
- `src/sportsbet/graph/router.py` — Added elif prop_analysis -> prop_quant_agent branch, updated routing table docstring

## Decisions Made

- KinematicAnalysis import moved from `TYPE_CHECKING` guard to runtime in agents.py — matches Phase 4/6 pattern (ContextSignals, KinematicAnalysis in state.py) for LangGraph `get_type_hints()` compatibility
- press_man_rate never accessed in adjustment function — always None per Phase 6 schema; only `geometric_mismatch_flag` consumed as the binary signal

## Deviations from Plan

None - plan executed exactly as written. The plan noted the 4th test (`test_kinematic_none_returns_unchanged`) was expected in the behavior block but absent from the file — added it as part of Task 1 per plan specification.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- PROP-04 requirement fully satisfied: kinematic signal integration is functional end-to-end
- PropResult.true_probability now reflects both historical SQL data and NGS separation geometry when applicable
- GraphState is fully extended for Phase 11 prop routing — any subsequent phase can read prop_result
- route_from_master supports prop_analysis request_type — ready for graph.py wiring if needed

---
*Phase: 11-nfl-player-prop-quant-engine*
*Completed: 2026-03-23*
