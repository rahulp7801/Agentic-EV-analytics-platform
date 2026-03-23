---
phase: 12-nba-player-prop-quant-engine
plan: "02"
subsystem: api
tags: [pydantic, langgraph, nba, probability, contextual-adjustment, decimal]

# Dependency graph
requires:
  - phase: 12-01
    provides: run_nba_prop_query NormalDist CDF executor, LEAGUE_AVG_PACE/DEF_RATING/REST_PENALTY/HOME_BOOST constants, PACE_ADJUSTED_PROPS frozenset
  - phase: 11-02
    provides: make_prop_quant_agent closure pattern, _apply_kinematic_adjustment structure to mirror
  - phase: 04-context-and-odds-ingestion
    provides: runtime import pattern for GraphState model fields (not TYPE_CHECKING)
provides:
  - NBAContextSignals Pydantic model in graph/models.py with ConfigDict(strict=True)
  - GraphState extended with nba_context_signals and nba_prop_result fields
  - make_nba_quant_agent closure factory in src/sportsbet/prop/nba_agents.py
  - _apply_nba_context_adjustments four-stage pipeline (pace, def_rating, rest, home)
affects: [phase-13-graph-routing, nba-prop-pipeline, route_from_master]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "NBAContextSignals with ConfigDict(strict=True) — no float coercion on Decimal fields, rejects float for Decimal at model boundary"
    - "Four-stage contextual adjustment pipeline: pace (PACE_ADJUSTED_PROPS only) -> def_ratio -> rest_penalty (b2b only) -> home_boost -> clamp [0.01, 0.99]"
    - "Adjustment ratios independently clamped: pace_ratio in [0.5, 1.5], def_ratio in [0.7, 1.3] before multiplication"
    - "Runtime import of NBAContextSignals in state.py (not TYPE_CHECKING) — LangGraph get_type_hints() compatibility, matches Phase 4/6 locked pattern"

key-files:
  created:
    - src/sportsbet/prop/nba_agents.py
  modified:
    - src/sportsbet/graph/models.py
    - src/sportsbet/graph/state.py
    - tests/test_nba_prop_executor.py
    - tests/test_models.py

key-decisions:
  - "NBAContextSignals imported at runtime in state.py (not TYPE_CHECKING) — matches Phase 4/6 locked pattern for LangGraph get_type_hints() compatibility"
  - "pace adjustment restricted to PACE_ADJUSTED_PROPS frozenset (points, rebounds, assists, pra) — threes/steals/blocks are efficiency props not possession-count props"
  - "REST_PENALTY applied only when rest_days == 0 (back-to-back); no penalty for rest_days >= 1"
  - "All adjustment ratios clamped independently before multiplication to prevent compounding extremes"

patterns-established:
  - "NBA contextual adjustment: four sequential stages with independent ratio clamping before final [0.01, 0.99] probability clamp"
  - "PACE_ADJUSTED_PROPS frozenset gates pace stage — volume props only, not efficiency props"

requirements-completed: [NBA-02]

# Metrics
duration: 8min
completed: 2026-03-23
---

# Phase 12 Plan 02: NBAQuantAgent Closure and Contextual Adjustment Pipeline Summary

**NBAContextSignals Pydantic model with strict=True + make_nba_quant_agent closure factory applying four-stage pace/def_rating/rest/home pipeline to NormalDist base probability**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-23T02:30:09Z
- **Completed:** 2026-03-23T02:38:12Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added NBAContextSignals to graph/models.py with ConfigDict(strict=True) enforcing Decimal field type safety
- Extended GraphState TypedDict with nba_context_signals and nba_prop_result fields via runtime import
- Implemented make_nba_quant_agent closure factory in nba_agents.py mirroring make_prop_quant_agent pattern
- Implemented _apply_nba_context_adjustments four-stage pipeline with independent ratio clamping
- Full test suite: 136 passed, 11 skipped (4 new TDD tests for adjustment pipeline)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add NBAContextSignals to graph/models.py and extend GraphState** - `33b1a90` (feat)
2. **Task 2: Implement make_nba_quant_agent closure with contextual adjustment pipeline** - `0199386` (feat)

_Note: TDD tasks follow RED (import fails) -> GREEN (implementation) pattern_

## Files Created/Modified

- `src/sportsbet/prop/nba_agents.py` - make_nba_quant_agent closure factory + _apply_nba_context_adjustments pipeline
- `src/sportsbet/graph/models.py` - NBAContextSignals Pydantic model with ConfigDict(strict=True)
- `src/sportsbet/graph/state.py` - GraphState extended with nba_context_signals and nba_prop_result, runtime import updated
- `tests/test_nba_prop_executor.py` - TDD tests for adjustment pipeline: rest_penalty, pace_adjustment_up, pace_not_applied_to_threes, context_none_returns_unchanged
- `tests/test_models.py` - TDD tests for NBAContextSignals: valid Decimal fields, rejects float, back-to-back rest_days=0

## Decisions Made

- NBAContextSignals uses ConfigDict(strict=True) — no float coercion means Decimal(str(...)) wrapping required by all callers
- Pace adjustment restricted to PACE_ADJUSTED_PROPS (points, rebounds, assists, pra) — threes/steals/blocks are efficiency-rate props not possession-volume props; pace does not increase their rates
- REST_PENALTY (0.03) applied only when rest_days == 0; rest_days >= 1 means no penalty regardless of actual rest count
- Adjustment ratios clamped independently before multiplication: pace_ratio clamped to [0.5, 1.5], def_ratio to [0.7, 1.3] — prevents compounding extreme ratios from producing nonsensical probabilities

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- make_nba_quant_agent is LangGraph-compatible and ready for Phase 13 graph routing wiring
- nba_context_signals field in GraphState is ready to be populated by NBA Context Agent
- route_from_master (Phase 13) needs to add "nba_prop_analysis" request_type routing to nba_quant_agent node

---
*Phase: 12-nba-player-prop-quant-engine*
*Completed: 2026-03-23*
