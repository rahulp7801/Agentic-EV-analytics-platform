---
phase: 02-agent-infrastructure
plan: "03"
subsystem: infra
tags: [langgraph, checkpointing, sqlite, pydantic-settings, kelly-criterion]

# Dependency graph
requires:
  - phase: 02-agent-infrastructure
    plan: "02"
    provides: "create_graph() factory and GraphState TypedDict with stub agents"
provides:
  - "create_graph(checkpointer=None) accepts optional checkpointer — backward-compatible"
  - "create_graph_with_sqlite() async factory writing to .checkpoints/sportsbet.sqlite via AsyncSqliteSaver"
  - "graph_fixture conftest fixture: MemorySaver + fresh UUID thread_id per test, no disk I/O"
  - "Settings.bankroll_usd=10000.0 and Settings.max_kelly_fraction=0.25 for Phase 5 Kelly Criterion"
  - "4 checkpoint tests: persist, replay, isolation, bankroll config fields"
affects:
  - phase-03-quant-agent
  - phase-04-arbitrage-agent
  - phase-05-kelly-sizing
  - phase-06-kinematic-agent

# Tech tracking
tech-stack:
  added:
    - langgraph-checkpoint-sqlite==3.0.3 (AsyncSqliteSaver for async graph.ainvoke checkpointing)
    - aiosqlite==0.22.1 (async SQLite driver for AsyncSqliteSaver)
  patterns:
    - "Optional checkpointer pattern: create_graph(checkpointer=None) — None compiles without checkpointing"
    - "Test isolation pattern: MemorySaver + uuid4 thread_id per fixture call — no disk I/O, no cleanup"
    - "Async SQLite factory: await create_graph_with_sqlite() creates graph with persistent aiosqlite connection"
    - "Settings-not-GraphState: bankroll/kelly fields live in config.py Settings, not graph state"

key-files:
  created:
    - .planning/phases/02-agent-infrastructure/02-03-SUMMARY.md
  modified:
    - src/sportsbet/config.py (bankroll_usd, max_kelly_fraction fields added)
    - src/sportsbet/graph/graph.py (create_graph checkpointer param + create_graph_with_sqlite factory)
    - src/sportsbet/graph/__init__.py (export create_graph_with_sqlite)
    - tests/conftest.py (graph_fixture with MemorySaver)
    - tests/test_graph.py (TestCheckpointing class with 4 tests)

key-decisions:
  - "AsyncSqliteSaver required instead of sync SqliteSaver — sync raises NotImplementedError on aget_tuple() with ainvoke() (Rule 1 auto-fix)"
  - "create_graph_with_sqlite() is async — must be awaited; callers use asyncio.run() from sync code"
  - "Persistent aiosqlite connection: await aiosqlite.connect(db_path) held for graph lifetime — caller responsible for lifecycle"
  - "langgraph-checkpoint-sqlite installed via manual wheel extraction to site-packages to avoid namespace collision with main langgraph package"

patterns-established:
  - "graph_fixture pattern: MemorySaver + fresh thread_id — all graph tests use this for isolation"
  - "Checkpointer injection: create_graph(checkpointer=saver) — tests pass MemorySaver, production passes AsyncSqliteSaver"

requirements-completed:
  - INFRA-04

# Metrics
duration: 6min
completed: 2026-03-10
---

# Phase 2 Plan 03: SqliteSaver Checkpointing Summary

**AsyncSqliteSaver-backed graph checkpointing with MemorySaver test isolation and bankroll config fields for Kelly Criterion sizing in Phase 5**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-11T01:01:57Z
- **Completed:** 2026-03-11T01:07:57Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Extended `create_graph()` with optional `checkpointer` param — backward-compatible with all Plan 02-02 tests
- Added `create_graph_with_sqlite()` async factory that writes checkpoints to `.checkpoints/sportsbet.sqlite` via AsyncSqliteSaver
- Added `graph_fixture` to conftest.py providing MemorySaver-backed graph + unique thread_id per test — zero disk I/O in test suite
- Added 4 `TestCheckpointing` tests: persist, replay, isolation, bankroll config assertions
- Added `bankroll_usd=10000.0` and `max_kelly_fraction=0.25` to Settings (not GraphState per CONTEXT.md decision)
- Full test suite: 13 graph tests + 10 model tests green; 30 passed, 7 skipped (DB tests require Postgres)

## Task Commits

Each task was committed atomically:

1. **Task 1: Config extensions and checkpointer factories** - `035deb5` (feat)
2. **Task 2: Checkpoint persist and replay tests** - `a51fe61` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `src/sportsbet/config.py` - Added bankroll_usd=10000.0 and max_kelly_fraction=0.25 fields
- `src/sportsbet/graph/graph.py` - Refactored create_graph() + added async create_graph_with_sqlite()
- `src/sportsbet/graph/__init__.py` - Added create_graph_with_sqlite to exports
- `tests/conftest.py` - Added graph_fixture with MemorySaver + fresh UUID thread_id
- `tests/test_graph.py` - Added TestCheckpointing class (4 tests)

## Decisions Made

- **AsyncSqliteSaver over sync SqliteSaver:** Plan specified sync SqliteSaver but `graph.ainvoke()` is async — sync SqliteSaver raises `NotImplementedError` on `aget_tuple()`. Using `AsyncSqliteSaver` from `langgraph.checkpoint.sqlite.aio` is required. (Rule 1 auto-fix)
- **Async factory function:** `create_graph_with_sqlite()` must be async because `AsyncSqliteSaver.__init__` calls `asyncio.get_running_loop()`. Callers use `asyncio.run(create_graph_with_sqlite())` from sync contexts.
- **Manual wheel extraction:** `pip install --target --upgrade` caused namespace collisions in the project's `site-packages/` directory (replacing `langgraph/` with only checkpoint package files). Resolved by extracting both langgraph-1.1.0, langgraph-checkpoint-4.0.1, and langgraph-checkpoint-sqlite-3.0.3 wheels manually to preserve all namespace package files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Replaced sync SqliteSaver with AsyncSqliteSaver for async graph compatibility**
- **Found during:** Task 1 verification (smoke test with asyncio.run + ainvoke)
- **Issue:** Plan specified `SqliteSaver.from_conn_string()` but that returns a context manager; even when instantiated directly, sync SqliteSaver raises `NotImplementedError: The SqliteSaver does not support async methods` when ainvoke calls `aget_tuple()`
- **Fix:** Changed `create_graph_with_sqlite()` to use `AsyncSqliteSaver` from `langgraph.checkpoint.sqlite.aio`, creating a persistent `aiosqlite.connect()` connection. Factory made `async def` because `AsyncSqliteSaver.__init__` requires running event loop.
- **Files modified:** `src/sportsbet/graph/graph.py`
- **Verification:** Smoke test produces `.checkpoints/sportsbet.sqlite` on disk after `asyncio.run(create_graph_with_sqlite())` then `await g.ainvoke(...)`
- **Committed in:** a51fe61 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - async incompatibility bug)
**Impact on plan:** Fix was necessary for correctness — sync SqliteSaver cannot work with async graph invocations. No scope creep.

## Issues Encountered

- **site-packages namespace collision:** Installing `langgraph-checkpoint-sqlite` with `pip install --target --upgrade` overwrote the main `langgraph/` package files, leaving only checkpoint subdirectory. Resolved by manually extracting all three wheels (langgraph, langgraph-checkpoint, langgraph-checkpoint-sqlite) in sequence using Python zipfile module to preserve all namespace package files.

## User Setup Required

None - no external service configuration required. The `.checkpoints/` directory is created automatically by `create_graph_with_sqlite()`.

## Next Phase Readiness

- Graph checkpointing infrastructure complete — Phase 3 agents can use `create_graph(checkpointer=saver)` with any LangGraph-compatible checkpointer
- `graph_fixture` provides clean test isolation for all future agent tests
- `bankroll_usd` and `max_kelly_fraction` in Settings ready for Phase 5 Kelly Criterion agent
- Concern: `create_graph_with_sqlite()` holds a persistent aiosqlite connection — Phase 5/6 should implement proper connection lifecycle management for production use

---
*Phase: 02-agent-infrastructure*
*Completed: 2026-03-10*
