---
phase: 06-kinematic-agent
plan: 01
subsystem: kinematic
tags: [pydantic, asyncpg, ngs, nfl, tdd, postgresql]

# Dependency graph
requires:
  - phase: 03-quant-engine
    provides: asyncpg pool.acquire pattern, Decimal(str()) wrapping, Pydantic strict=True gate pattern
  - phase: 01-data-foundation
    provides: ngs_stats PostgreSQL table with avg_separation, avg_cushion, press_man_rate (nullable)
provides:
  - KinematicParams Pydantic model (season ge=2016 NGS boundary gate)
  - KinematicAnalysis Pydantic output model (Optional[Decimal] NGS fields, press_man_rate=None)
  - check_ngs_availability(pool, season) async function (KINE-03)
  - run_matchup_query(pool, params) async function returning KinematicAnalysis (KINE-01)
  - make_kinematic_agent(pool) closure factory in graph/agents.py
  - kinematic_result field in GraphState
  - 6 TDD tests covering KINE-01 and KINE-03
affects:
  - 06-02-PLAN (wraps these primitives as LangGraph node and extends graph/graph.py)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Closure factory pattern (make_kinematic_agent) matches Phases 3-5 convention
    - Decimal(str(row["field"])) wrapping for asyncpg NUMERIC columns
    - One-way dependency: kinematic/ never imports from graph/; graph/agents.py imports from kinematic/
    - Season boundary enforced at Pydantic level (ge=2016) not only at DB guard level
    - press_man_rate=None always — forward-compat column that is NULL in all current ngs_stats rows

key-files:
  created:
    - src/sportsbet/kinematic/__init__.py
    - src/sportsbet/kinematic/models.py
    - src/sportsbet/kinematic/availability.py
    - src/sportsbet/kinematic/matchup.py
    - tests/test_kinematic.py
  modified:
    - src/sportsbet/graph/agents.py
    - src/sportsbet/graph/state.py

key-decisions:
  - "KinematicParams.season uses Field(ge=2016) not ge=1999 — NGS data boundary enforced at Pydantic layer"
  - "press_man_rate=None always on KinematicAnalysis — column is NULL in all ngs_stats rows; forward-compat only"
  - "make_kinematic_agent(pool) added to graph/agents.py in Plan 01 (not deferred to Plan 02) — required by test_unavailable_season_returns_none_fields"
  - "kinematic_result: Optional[KinematicAnalysis] added to GraphState following Phase 4 runtime import pattern for ContextSignals"
  - "SEPARATION_THRESHOLD=Decimal('2.5') hardcoded at module level — documented as configurable heuristic"

patterns-established:
  - "Kinematic isolation: src/sportsbet/kinematic/ never imports from graph/; graph/agents.py imports from kinematic/ only"
  - "TDD: test file written first (RED), implementation second (GREEN), all 6 tests pass clean"

requirements-completed: [KINE-01, KINE-03]

# Metrics
duration: 5min
completed: 2026-03-21
---

# Phase 6 Plan 01: Kinematic Subpackage Summary

**Pydantic-gated NGS separation query layer with geometric mismatch flag, season availability guard (2016+), and make_kinematic_agent closure factory wired to GraphState**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-21T19:01:06Z
- **Completed:** 2026-03-21T19:06:34Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 7 (5 created, 2 modified)

## Accomplishments
- Built `src/sportsbet/kinematic/` package (4 modules) with zero graph/ imports — strict one-way dependency
- KinematicParams rejects season < 2016 (NGS boundary) at Pydantic validation layer before any SQL
- run_matchup_query computes geometric_mismatch_flag from SEPARATION_THRESHOLD=Decimal("2.5") with Decimal(str()) wrapping
- make_kinematic_agent closure factory integrated into graph/agents.py following Phase 3-5 pattern
- 6 TDD tests all green; full 85-test suite passes with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: kinematic subpackage scaffold — models, availability guard, matchup executor with test stubs** - `9966fa8` (feat)

## Files Created/Modified
- `src/sportsbet/kinematic/__init__.py` — package marker with isolation docstring
- `src/sportsbet/kinematic/models.py` — KinematicParams (season ge=2016), KinematicAnalysis (press_man_rate=None always)
- `src/sportsbet/kinematic/availability.py` — check_ngs_availability(pool, season) async COUNT(*) guard
- `src/sportsbet/kinematic/matchup.py` — run_matchup_query with _SEPARATION_QUERY, SEPARATION_THRESHOLD, Decimal wrapping
- `tests/test_kinematic.py` — 6 TDD tests covering KINE-01 and KINE-03
- `src/sportsbet/graph/agents.py` — make_kinematic_agent(pool) closure factory added (Phase 6)
- `src/sportsbet/graph/state.py` — kinematic_result: Optional[KinematicAnalysis] field added

## Decisions Made
- **KinematicParams.season ge=2016:** NGS data available from 2016 only (RESEARCH.md Pitfall 2). Using ge=1999 (QuantParams value) would allow requests that return zero rows. Pydantic constraint is the primary gate; DB availability check is the fallback.
- **press_man_rate=None always:** Column exists in ngs_stats as a nullable forward-compat placeholder from Phase 1. Raw NGS data does not include press/man rate. Never queried; always None on KinematicAnalysis.
- **make_kinematic_agent in Plan 01:** Test 3 (`test_unavailable_season_returns_none_fields`) requires make_kinematic_agent to validate the full unavailability return path. Added to agents.py in this plan rather than deferring to Plan 02.
- **kinematic_result in GraphState:** Follows Phase 4 runtime import pattern — `from sportsbet.kinematic.models import KinematicAnalysis` at module level in state.py (not TYPE_CHECKING guard), per Phase 4 decision that LangGraph's get_type_hints() cannot resolve TYPE_CHECKING-only imports.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added make_kinematic_agent to agents.py in Plan 01**
- **Found during:** Task 1 (test stub writing)
- **Issue:** test_unavailable_season_returns_none_fields behavior spec requires testing `make_kinematic_agent` returning `{"kinematic_result": None}` when availability is False. Plan 01 action steps don't mention agents.py, but test 3 cannot pass without it.
- **Fix:** Implemented `make_kinematic_agent(pool)` closure factory in graph/agents.py and added `kinematic_result` field to GraphState.
- **Files modified:** src/sportsbet/graph/agents.py, src/sportsbet/graph/state.py
- **Verification:** All 6 tests pass; full 85-test suite green
- **Committed in:** 9966fa8 (Task 1 commit)

**2. [Rule 1 - Bug] Fixed Pydantic deprecation warning for model_fields access**
- **Found during:** Task 1 (test run)
- **Issue:** `analysis.model_fields` (instance access) triggers PydanticDeprecatedSince211 warning; correct form is `KinematicAnalysis.model_fields` (class access)
- **Fix:** Changed instance access to class access in test_kinematic_analysis_has_no_quant_fields
- **Files modified:** tests/test_kinematic.py
- **Verification:** No warnings in final test run
- **Committed in:** 9966fa8 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 bug)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered
None beyond the two deviations documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `check_ngs_availability`, `run_matchup_query`, `KinematicParams`, `KinematicAnalysis` all importable from `sportsbet.kinematic`
- `make_kinematic_agent(pool)` ready in `graph/agents.py`
- `kinematic_result` field in `GraphState`
- Plan 02 can wire `make_kinematic_agent` as a LangGraph node in `graph/graph.py` and extend `route_from_master` for `request_type="kinematic_analysis"`

---
*Phase: 06-kinematic-agent*
*Completed: 2026-03-21*
