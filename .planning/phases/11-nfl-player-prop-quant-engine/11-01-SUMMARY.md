---
phase: 11-nfl-player-prop-quant-engine
plan: 01
subsystem: database
tags: [asyncpg, pydantic, statsmodels, wilson-ci, tdd, sql-injection-prevention]

# Dependency graph
requires:
  - phase: 03-quant-engine
    provides: QueryBuilder/executor pattern (PropQueryBuilder mirrors quant/query_builder.py exactly)
  - phase: 10-player-prop-and-nba-data-layer
    provides: PropParams, PropResult Pydantic models and player_stats table schema
provides:
  - src/sportsbet/prop/ subpackage (PropQueryBuilder, run_prop_query, make_prop_quant_agent)
  - PropQueryBuilder.build() with PROP_COLUMN_MAP covering all 11 NFL prop types
  - run_prop_query with Wilson CI and MIN_PROP_SAMPLE_SIZE=30 gate
  - make_prop_quant_agent closure factory with kinematic adjustment stub for Plan 02
  - PropParams.prop_type extended: completions, attempts, carries, targets added
affects:
  - 11-02-PLAN (kinematic integration fills _apply_kinematic_adjustment stub)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - PropQueryBuilder.build() mirrors QueryBuilder.build() — static PROP_COLUMN_MAP allowlist substitution, $N positional params only
    - Wilson CI bounds via Decimal(str(round(x, 6))) — strict=True Pydantic guard prevents float assignment
    - float(params.line) as args[2] — avoids asyncpg NUMERIC vs SMALLINT operator ambiguity
    - _apply_kinematic_adjustment(result, None, prop_type) stub — returns result unchanged when kinematic=None

key-files:
  created:
    - src/sportsbet/prop/__init__.py
    - src/sportsbet/prop/query_builder.py
    - src/sportsbet/prop/executor.py
    - src/sportsbet/prop/agents.py
    - tests/test_prop_query_builder.py
    - tests/test_prop_executor.py
  modified:
    - src/sportsbet/graph/models.py

key-decisions:
  - "PROP_COLUMN_MAP keys are Python string literals keyed by prop_type Literal — never user input; allowlist substitution into SQL template is safe"
  - "float(params.line) as args[2] in PropQueryBuilder.build() — avoids asyncpg NUMERIC/SMALLINT operator ambiguity (same pattern as quant executor)"
  - "mean_stat = Decimal(str(round(float(row['mean_val']), 2))) — 2dp for display; None guard when AVG returns NULL"
  - "_apply_kinematic_adjustment stub returns result unchanged when kinematic=None — Plan 02 fills in delta/clamping logic"
  - "PROP_ALLOWED_FILTER_KEYS = frozenset({'week', 'team'}) — narrower than quant's frozenset (player stats filter domain)"
  - "PropParams.prop_type extended with completions, attempts, carries, targets — backward-compatible Literal addition per PROP-03"

patterns-established:
  - "PropQueryBuilder pattern: PROP_COLUMN_MAP + PROP_ALLOWED_FILTER_KEYS + _NFL_PROP_TEMPLATE with {col} substitution from allowlist"
  - "Kinematic adjustment stub: _apply_kinematic_adjustment(result, None, prop_type) as no-op placeholder for Plan 02"

requirements-completed: [PROP-03]

# Metrics
duration: 4min
completed: 2026-03-23
---

# Phase 11 Plan 01: PropQueryBuilder TDD — SQL Gate and Wilson CI Summary

**NFL player prop quant engine subpackage: PropQueryBuilder Pydantic gate -> parameterized player_stats SQL -> Wilson CI -> PropResult with Decimal fields**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-23T01:41:29Z
- **Completed:** 2026-03-23T01:45:49Z
- **Tasks:** 2 (TDD: Wave 0 RED + Wave 1 GREEN)
- **Files modified:** 7

## Accomplishments

- PropQueryBuilder with PROP_COLUMN_MAP covering all 11 NFL prop types — structural SQL injection prevention via column name allowlist
- run_prop_query with Wilson CI (statsmodels), MIN_PROP_SAMPLE_SIZE=30 gate, and Decimal wrapping for strict Pydantic compliance
- make_prop_quant_agent closure factory with _apply_kinematic_adjustment stub ready for Plan 02 kinematic integration
- PropParams.prop_type Literal extended with completions, attempts, carries, targets (backward-compatible PROP-03 requirement)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — test stubs + PropParams extension + prop subpackage scaffold** - `42cba84` (test)
2. **Task 2: GREEN — PropQueryBuilder, run_prop_query, make_prop_quant_agent** - `291b717` (feat)

_Note: TDD tasks have two commits (test RED Wave 0 -> feat GREEN Wave 1)_

## Files Created/Modified

- `src/sportsbet/prop/__init__.py` - Package marker with module docstring
- `src/sportsbet/prop/query_builder.py` - PropQueryBuilder with PROP_COLUMN_MAP and PROP_ALLOWED_FILTER_KEYS
- `src/sportsbet/prop/executor.py` - run_prop_query with Wilson CI and MIN_PROP_SAMPLE_SIZE gate
- `src/sportsbet/prop/agents.py` - make_prop_quant_agent closure factory with kinematic stub
- `tests/test_prop_query_builder.py` - PROP-03 SQL gate tests (3 tests, all green)
- `tests/test_prop_executor.py` - PROP-03 executor tests + PROP-04 xfail stubs (6 tests)
- `src/sportsbet/graph/models.py` - PropParams.prop_type extended with 4 new NFL types

## Decisions Made

- PROP_COLUMN_MAP keys are Python string literals keyed by prop_type Literal — allowlist substitution into SQL template is structurally safe; no user input reaches the SQL string
- float(params.line) as args[2] — avoids asyncpg NUMERIC/SMALLINT operator ambiguity (same guard as quant/executor.py)
- mean_stat uses Decimal(str(round(float(row["mean_val"]), 2))) at 2dp for display; None guard when AVG returns NULL (no non-NULL rows)
- _apply_kinematic_adjustment stub returns result unchanged when kinematic=None — clean no-op that Plan 02 replaces with real delta/clamping
- PROP_ALLOWED_FILTER_KEYS = frozenset({"week", "team"}) — narrower scope than quant (player stats domain)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02 (kinematic integration) can import make_prop_quant_agent and implement _apply_kinematic_adjustment with real KinematicAnalysis delta logic
- PROP-04 xfail test stubs in test_prop_executor.py serve as the RED phase for Plan 02 kinematic tests
- Full test suite: 111 passed, 11 skipped (DB-gated), 3 xfailed (PROP-04 stubs) — no regressions

---
*Phase: 11-nfl-player-prop-quant-engine*
*Completed: 2026-03-23*
