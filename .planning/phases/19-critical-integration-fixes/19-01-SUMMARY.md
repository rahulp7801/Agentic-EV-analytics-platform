---
phase: 19-critical-integration-fixes
plan: 01
subsystem: api
tags: [python, pydantic, langgraph, postgresql, player-props, nba, nfl, pytest]

# Dependency graph
requires:
  - phase: 18-situational-game-log-prop-queries
    provides: PropParams.teammate_out field, situational_params in GraphState, conditional WHERE clauses in PropQueryBuilder/NBAQueryBuilder
  - phase: 14-prop-integration-gap-closure
    provides: write_player_prop_snapshot in context_agent, PlayerPropSnapshotCreate model
provides:
  - INT-2 closed: PlayerPropSnapshotCreate uses sport=sport variable; NBA prop snapshots stored with sport='nba'
  - INT-1 NFL closed: prop_quant_agent reads situational_params and forwards teammate_out to PropParams
  - INT-1 NBA closed: nba_quant_agent reads situational_params and forwards teammate_out to PropParams
  - 5 regression tests covering INT-2 sport tag and INT-1 teammate_out bridge (NFL + NBA)
affects:
  - downstream pipeline invocations that rely on correct sport tag in player_prop_snapshots
  - Phase 18 conditional WHERE clauses (teammate_out INTERVAL join) now fire in automated runs

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "state.get('situational_params') or {} bridge pattern for Optional GraphState fields before PropParams construction"
    - "sport=sport variable substitution instead of hardcoded literals inside context_agent closure"

key-files:
  created:
    - tests/test_prop_integration_fixes.py
  modified:
    - src/sportsbet/graph/agents.py
    - src/sportsbet/prop/agents.py
    - src/sportsbet/prop/nba_agents.py

key-decisions:
  - "INT-2: sport=sport uses variable already in scope at line 219 (state.get('sport') or 'nfl') — single-token change, no new imports"
  - "INT-1 bridge pattern: state.get('situational_params') or {} handles both None and absent-key cases; or None on teammate_out normalizes empty list to None for PropQueryBuilder if-check compatibility"

patterns-established:
  - "Bridge pattern for Optional GraphState fields: state.get('field') or {} then .get('subkey') or None — use before any PropParams construction when field is Optional in GraphState"

requirements-completed: [PROP-01]

# Metrics
duration: 5min
completed: 2026-03-26
---

# Phase 19 Plan 01: Critical Integration Fixes Summary

**Surgical two-line bridge in prop_quant_agent and nba_quant_agent forwards situational_params.teammate_out_signals to PropParams, and a single-token fix changes hardcoded sport='nfl' to sport=sport in PlayerPropSnapshotCreate**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-26T04:26:56Z
- **Completed:** 2026-03-26T04:32:05Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Closed INT-2: NBA prop snapshots now stored with sport='nba'; hardcoded 'nfl' literal removed from agents.py line 304
- Closed INT-1 (NFL + NBA): Phase 18 teammate_out conditional WHERE clauses now fire in automated pipeline runs when injury context is present
- Test suite advanced from 188 to 193 passed with 5 new regression tests; 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — Create failing test stubs for INT-1 and INT-2 fixes** - `936dff8` (test)
2. **Task 2: Apply INT-2 and INT-1 fixes — turn tests GREEN** - `360072b` (feat)

## Files Created/Modified

- `tests/test_prop_integration_fixes.py` - 5 regression tests: INT-2 sport tag (NBA + NFL default) + INT-1 teammate_out bridge (NFL + NBA + backward compat)
- `src/sportsbet/graph/agents.py` - INT-2 fix: `sport="nfl"` literal changed to `sport=sport` variable at PlayerPropSnapshotCreate line 304
- `src/sportsbet/prop/agents.py` - INT-1 fix: situational_params bridge + teammate_out=teammate_out added to PropParams in prop_quant_agent
- `src/sportsbet/prop/nba_agents.py` - INT-1 NBA parity: identical bridge pattern applied to nba_quant_agent PropParams construction

## Decisions Made

- INT-2 fix uses `sport=sport` (variable already in scope at line 219 as `state.get("sport") or "nfl"`) — zero new imports, zero restructuring
- INT-1 bridge uses `state.get("situational_params") or {}` to handle both `None` value and absent-key cases; `or None` on teammate_out normalizes `[]` to `None` (PropQueryBuilder checks `if params.teammate_out:` which correctly skips both)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- PROP-01 fully satisfied: live NFL and NBA player prop odds from The Odds API write PlayerPropSnapshot rows with correct sport tags
- Phase 18 SC-3/SC-4 conditional WHERE clauses (teammate_out INTERVAL join) now activate when injury context is present in automated pipeline runs
- v1.0 milestone gap closure complete for INT-1 and INT-2

---
*Phase: 19-critical-integration-fixes*
*Completed: 2026-03-26*
