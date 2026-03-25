---
phase: 18-situational-game-log-prop-queries
plan: 02
subsystem: api
tags: [pydantic, langgraph, graphstate, context-agent, typeddict, optional-fields]

# Dependency graph
requires:
  - phase: 18-01
    provides: NBAPlayerGameLog schema and ingestion pipeline for situational game-log data
provides:
  - PropParams with four Optional situational filter fields (last_n_games, teammate_out, opponent_team, home_away)
  - GraphState.situational_params TypedDict field (last entry)
  - _extract_situational_params() pure function in agents.py
  - make_context_agent returns situational_params key in state dict
  - 9 SC-3 Wave 0 tests (GREEN)
affects:
  - 18-03 (PropQueryBuilder consumes PropParams.last_n_games, opponent_team, home_away, teammate_out)
  - Any future agent reading GraphState.situational_params

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Optional TypedDict field pattern: dict[str, Any] | None with type: ignore[misc] comment (matches Phase 14 prop_filters pattern)
    - Pure helper function above closure factory for co-location and testability
    - TDD Wave 0 stubs: FAILED (not ERROR) RED indicators using direct pytest.raises

key-files:
  created:
    - tests/test_prop_params_situational.py
    - tests/test_context_agent_params.py
  modified:
    - src/sportsbet/graph/models.py
    - src/sportsbet/graph/state.py
    - src/sportsbet/graph/agents.py

key-decisions:
  - "PropParams.home_away: Optional[Literal['home', 'away']] — Literal union enforces strict validation; 'center' raises ValidationError at Pydantic layer before any SQL"
  - "_extract_situational_params() placed as module-level private function above make_context_agent — co-located with usage, pure (no async/DB), directly testable"
  - "situational_params is None when no Out/Inactive flags — avoids injecting empty noise dict into state for non-injury scenarios"
  - "ContextSignals imported at runtime in agents.py (not TYPE_CHECKING) for _extract_situational_params type annotation — follows Phase 4 locked pattern for LangGraph get_type_hints() compatibility"

patterns-established:
  - "Optional GraphState field added as last TypedDict entry with type: ignore[misc] and inline Phase comment"
  - "Context agent returns partial state dict with new key on every invocation (key present, value may be None) — LangGraph merger handles None gracefully"

requirements-completed: [SC-3]

# Metrics
duration: 7min
completed: 2026-03-25
---

# Phase 18 Plan 02: Situational Params Contracts Summary

**PropParams extended with four Optional situational filter fields and GraphState gains situational_params, wired via _extract_situational_params in make_context_agent**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-25T18:17:47Z
- **Completed:** 2026-03-25T18:24:50Z
- **Tasks:** 3 (TDD: RED stubs, GREEN implementation, GREEN injection)
- **Files modified:** 5

## Accomplishments

- PropParams accepts last_n_games, teammate_out, opponent_team, home_away as Optional fields with None defaults — existing callers pass without those fields and it still validates
- GraphState.situational_params declared as last TypedDict entry with dict[str, Any] | None type
- make_context_agent closure now injects situational_params into its return state dict via _extract_situational_params() — non-None when Out/Inactive injury flags exist
- All 9 SC-3 tests pass GREEN; full suite 179 passed, 11 skipped, 2 xfailed (no regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 test stubs for SC-3** - `784e29b` (test)
2. **Task 2: Extend PropParams and GraphState** - `f6c6314` (feat)
3. **Task 3: Wire situational_params injection into make_context_agent** - `453393a` (feat)

**Plan metadata:** (docs commit pending)

_Note: TDD tasks had three commits — RED stubs, GREEN production code, GREEN injection wiring_

## Files Created/Modified

- `tests/test_prop_params_situational.py` - 7 PropParams optional field validation tests (SC-3 Wave 0)
- `tests/test_context_agent_params.py` - GraphState annotation check + make_context_agent return dict test
- `src/sportsbet/graph/models.py` - PropParams extended with 4 Optional situational fields and updated docstring
- `src/sportsbet/graph/state.py` - GraphState.situational_params added as last TypedDict field with docstring entry
- `src/sportsbet/graph/agents.py` - _extract_situational_params() pure helper + situational_params key in make_context_agent return dict

## Decisions Made

- PropParams.home_away uses `Optional[Literal["home", "away"]]` — strict Literal union; passing "center" raises ValidationError at Pydantic layer, never reaches SQL
- _extract_situational_params() is a module-level private function (not inline lambda) — co-located above make_context_agent, pure (no async/DB), individually testable
- situational_params returns None (not empty dict) when no Out/Inactive players — avoids injecting noise into state for games with no relevant injury context
- The return key is always present in context_agent's state dict — LangGraph merges via reducer; Plan 03 PropQueryBuilder accesses via state.get("situational_params") to be safe

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- PropParams situational filter contract is stable — Plan 03 PropQueryBuilder can consume last_n_games, opponent_team, home_away, teammate_out fields
- GraphState.situational_params provides teammate_out_signals list to Plan 03 query builders
- All interfaces are backward-compatible; no existing callers need changes

---
*Phase: 18-situational-game-log-prop-queries*
*Completed: 2026-03-25*
