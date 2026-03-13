---
phase: 03-quant-engine
plan: "01"
subsystem: database
tags: [asyncpg, pydantic, statsmodels, wilson-ci, sql, langraph, quant]

requires:
  - phase: 02-agent-infrastructure
    provides: "QuantParams and QuantResult Pydantic models, GraphState, async graph skeleton, stub quant_agent"
  - phase: 01-data-foundation
    provides: "asyncpg create_async_pool, play_by_play schema"

provides:
  - "src/sportsbet/quant/ subpackage (query_builder.py, executor.py)"
  - "QueryBuilder.build() — parameterized SQL with FilterKey allowlist guard"
  - "run_quant_query() — async executor with Wilson CI via statsmodels"
  - "make_quant_agent(pool) — async closure factory replacing sync stub"
  - "MIN_SAMPLE_SIZE=30 gate returning insufficient_sample on thin data"

affects:
  - "04-context-agent"
  - "05-arbitrage-agent"
  - "06-kinematic-agent"

tech-stack:
  added:
    - "statsmodels>=0.14 (proportion_confint Wilson CI)"
  patterns:
    - "Static SQL template dispatch by Literal stat_type (no dynamic column selection)"
    - "ALLOWED_FILTER_KEYS frozenset allowlist — column names never from user input"
    - "Decimal(str(round(x,6))) wrapping of float CI bounds for strict=True Pydantic compat"
    - "Closure factory pattern for async LangGraph nodes with injected pool dependency"
    - "Backward-compat quant_agent stub preserved alongside make_quant_agent"

key-files:
  created:
    - "src/sportsbet/quant/__init__.py"
    - "src/sportsbet/quant/query_builder.py"
    - "src/sportsbet/quant/executor.py"
    - "tests/test_quant.py"
  modified:
    - "pyproject.toml (statsmodels dep)"
    - "src/sportsbet/graph/agents.py (make_quant_agent, get_or_create_pool)"
    - "src/sportsbet/graph/graph.py (quant_node param, create_graph_with_sqlite pool param)"

key-decisions:
  - "ALLOWED_FILTER_KEYS frozenset is the structural SQL injection prevention layer — column names are never user-supplied, only values go into $N params"
  - "Literal stat_type (Pydantic) + static _QUERY_TEMPLATES dict = no dynamic SQL construction; QueryBuilder.build() never calls any string format with user data for column selection"
  - "Decimal(str(round(x,6))) for Wilson CI bounds — raw statsmodels float rejected by QuantResult strict=True model"
  - "MIN_SAMPLE_SIZE=30 gate returns QuantResult(data_source='insufficient_sample') rather than a probability — callers must handle None true_probability"
  - "Sync stub quant_agent preserved in agents.py for Phase 2 test backward-compat — quant_node=None in create_graph() selects it"
  - "make_quant_agent closes over asyncpg pool — pool lifecycle managed externally; no pool creation inside node"

patterns-established:
  - "FilterKey guard: frozenset allowlist for SQL column names, structlog warning on drop, silently continues"
  - "TDD Red-Green on quant module: stub tests first, then QueryBuilder, then executor"
  - "Mock asyncpg pool pattern: MagicMock pool + AsyncMock conn + _async_cm context manager for unit tests without DB"

requirements-completed: [QUANT-01, QUANT-03]

duration: 7min
completed: 2026-03-13
---

# Phase 3 Plan 01: Quant Engine — SQL Gate and Wilson CI Summary

**Two-stage SQL injection prevention gate (QuantParams Literal validation + QueryBuilder FilterKey allowlist) with asyncpg executor returning Wilson CI Decimal bounds, replacing the fixture stub quant_agent with an async closure factory**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-13T19:18:58Z
- **Completed:** 2026-03-13T19:25:51Z
- **Tasks:** 3 (TDD: RED scaffold + GREEN QueryBuilder + GREEN executor/agents/graph)
- **Files modified:** 7

## Accomplishments

- QuantParams Pydantic validation (Literal stat_type, season ge=1999) prevents malformed payloads from reaching SQL — validated before QueryBuilder.build() is ever called
- QueryBuilder.build() uses static template dispatch (3 templates: passing/rushing/receiving) + ALLOWED_FILTER_KEYS frozenset allowlist; user values only in asyncpg $N positional args, never in SQL string
- run_quant_query() executes parameterized queries with MIN_SAMPLE_SIZE=30 gate and Wilson CI via statsmodels; CI bounds converted to Decimal(str(...)) before QuantResult strict=True validation
- make_quant_agent(pool) closure factory replaces sync stub — async LangGraph node with injected pool; sync stub preserved for Phase 2 backward-compat
- Full test suite: 45 passed, 9 skipped (DB-gated), 0 regressions across all Phase 1 and Phase 2 tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 scaffold — test stubs, quant subpackage, statsmodels dep (RED)** - `e8bc1fb` (test)
2. **Task 2: QueryBuilder — static template dispatch with FilterKey guard (GREEN)** - `923f116` (feat)
3. **Task 3: executor.py + real quant_agent closure — replace stub (GREEN)** - `455e6c2` (feat)

_Note: TDD tasks — Task 1 is RED commit, Tasks 2-3 are GREEN commits_

## Files Created/Modified

- `src/sportsbet/quant/__init__.py` - quant subpackage marker
- `src/sportsbet/quant/query_builder.py` - QueryBuilder class with ALLOWED_FILTER_KEYS guard and static SQL templates
- `src/sportsbet/quant/executor.py` - run_quant_query async fn, Wilson CI, MIN_SAMPLE_SIZE gate
- `tests/test_quant.py` - 8 test functions (6 unit, 2 DB-gated integration)
- `pyproject.toml` - added statsmodels>=0.14 dependency
- `src/sportsbet/graph/agents.py` - added make_quant_agent closure factory and get_or_create_pool; stub preserved
- `src/sportsbet/graph/graph.py` - create_graph() quant_node param; create_graph_with_sqlite() pool param

## Decisions Made

- ALLOWED_FILTER_KEYS frozenset (not runtime user input) is the structural SQL column injection prevention — values are always $N params, column names come only from the static set
- Decimal(str(round(x, 6))) wrapping for CI bounds — statsmodels returns float; QuantResult strict=True rejects float directly
- MIN_SAMPLE_SIZE=30 gate: thin queries return QuantResult(data_source="insufficient_sample", true_probability=None) to signal unreliable data
- Sync quant_agent stub preserved alongside make_quant_agent to avoid breaking 45 existing Phase 2 tests
- make_quant_agent(pool) follows closure factory pattern — pool injected at construction time, not created inside the node

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None — all tests passed on first run for each GREEN phase. Mock asyncpg pool test pattern (MagicMock + AsyncMock + _async_cm) worked correctly for both insufficient_sample and adequate_sample test cases.

## User Setup Required

None — no external service configuration required. SPORTSBET_TEST_DATABASE_URL enables the 2 DB-gated integration tests but is not required for the 6 unit tests.

## Next Phase Readiness

- quant subpackage is complete and wired into graph — Phase 4 Context Agent can now call make_quant_agent(pool) with real QuantParams built from context stream data
- QueryBuilder templates cover passing/rushing/receiving; Phase 6 Kinematic Agent will add NGS-specific templates
- Arbitrage Agent (Phase 5) can read QuantResult.true_probability for +EV comparison — non-None only when sample_size >= 30
- All existing Phase 1 and Phase 2 tests remain green with zero regressions

---
*Phase: 03-quant-engine*
*Completed: 2026-03-13*
