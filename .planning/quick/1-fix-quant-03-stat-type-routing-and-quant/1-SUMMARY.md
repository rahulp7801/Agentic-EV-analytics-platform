---
phase: quick-1
plan: 1
subsystem: graph/agents, ingestion
tags: [quant-03, quant-04, stat-type, games-ingestion, cli]
dependency_graph:
  requires: [src/sportsbet/graph/state.py, src/sportsbet/graph/agents.py, src/sportsbet/ingestion/cli.py]
  provides: [GraphState.stat_type, ingest_games_seasons, CLI --games flag]
  affects: [make_quant_agent, BacktestEngine, odds_snapshots LEFT JOIN]
tech_stack:
  added: [sqlalchemy.dialects.postgresql.insert (pg_insert ON CONFLICT DO NOTHING)]
  patterns: [TDD RED/GREEN, closure-local import patching via origin module, Polars-first write path]
key_files:
  created: [src/sportsbet/ingestion/games.py, tests/test_ingestion_games.py]
  modified: [src/sportsbet/graph/state.py, src/sportsbet/graph/agents.py, src/sportsbet/ingestion/cli.py, tests/test_quant.py]
decisions:
  - "patch at origin (sportsbet.quant.executor.run_quant_query) required — run_quant_query is imported inside make_quant_agent closure so consumer-path patching fails; make_quant_agent called inside patch context to capture mock"
  - "polars.DataFrame.to_pandas patched at polars module level in games ingestion tests — pyarrow not installed in test environment; rows intercepted via pg_insert.values() tracker"
  - "ingest_games_seasons placed outside if not args.pbp_only block — games ingestion is independent of PBP flag"
  - "CLI test mocks ingest_player_stats_seasons and ingest_ngs_seasons to prevent actual nflreadpy network calls during --games CLI test"
metrics:
  duration: 9min
  completed: 2026-03-27
  tasks_completed: 2
  files_modified: 6
---

# Quick-1 Plan 1: Fix QUANT-03 stat_type Routing and QUANT-04 Games Ingestion Summary

**One-liner:** stat_type flows from GraphState into QuantParams via `state.get("stat_type") or "passing"`; games table populated via `ingest_games_seasons()` using `nflreadpy.load_schedules()` with `--games` CLI flag.

## What Was Built

### Task 1: stat_type routing fix (QUANT-03)

- `src/sportsbet/graph/state.py`: Added `stat_type: str | None` as the last field in `GraphState` TypedDict with full docstring documentation
- `src/sportsbet/graph/agents.py`: Fixed hardcoded `stat_type="passing"` in `make_quant_agent` closure to `state.get("stat_type") or "passing"` — handles both absent key (safe via `.get()`) and explicit `None` value
- `tests/test_quant.py`: Added 4 new tests (QUANT-03 routing, absent default, None default, GraphState field presence)

### Task 2: games table ingestion (QUANT-04)

- `src/sportsbet/ingestion/games.py`: New module — `ingest_games_seasons(seasons, engine)` using `nfl.load_schedules()`, column whitelist, `gameday -> game_date` rename, NULL PK filter, `pg_insert ON CONFLICT DO NOTHING`
- `src/sportsbet/ingestion/cli.py`: Added `--games` flag; `ingest_games_seasons()` called independently (not inside `if not args.pbp_only`)
- `tests/test_ingestion_games.py`: 4 new tests — load_schedules called once, schema column mapping, ON CONFLICT idempotency, CLI --games wiring

## Verification Results

```
tests/test_quant.py: 10 passed, 2 skipped
tests/test_ingestion_games.py: 4 passed
Full suite: 223 passed, 11 skipped, 2 xfailed (0 failures)
```

Smoke tests:
- `from sportsbet.ingestion.games import ingest_games_seasons; from sportsbet.graph.state import GraphState` — imports ok
- `typing.get_type_hints(GraphState)['stat_type']` — `str | None` confirmed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Closure-local import requires origin-path patching in tests**
- **Found during:** Task 1 RED phase
- **Issue:** `run_quant_query` is imported inside the `make_quant_agent` closure body (`from sportsbet.quant.executor import run_quant_query`), not at module level. `patch("sportsbet.graph.agents.run_quant_query")` fails with AttributeError.
- **Fix:** Patched at origin (`sportsbet.quant.executor.run_quant_query`) with `make_quant_agent` called inside the patch context so the closure-local import captures the mock.
- **Files modified:** `tests/test_quant.py`

**2. [Rule 3 - Blocking] pyarrow not installed — df.to_pandas() fails in test environment**
- **Found during:** Task 2 GREEN phase
- **Issue:** `polars.DataFrame.to_pandas()` requires `pyarrow` which is not installed. Test would fail when real Polars DataFrame reaches `to_pandas()`.
- **Fix:** Patched `polars.DataFrame.to_pandas` at the polars module level in tests; rows intercepted via `pg_insert.values()` tracker before `to_pandas()` runs; CLI test additionally mocks `ingest_player_stats_seasons` and `ingest_ngs_seasons` to prevent network calls.
- **Files modified:** `tests/test_ingestion_games.py`

## Self-Check: PASSED

All created/modified files confirmed present on disk. All 4 commits verified in git log:
- `38cf77a` test(quick-1-1): add failing tests for QUANT-03 stat_type routing
- `2f93051` feat(quick-1-1): fix QUANT-03 stat_type routing — read from GraphState
- `e1ad8ea` test(quick-1-1): add failing tests for QUANT-04 games ingestion
- `e5f071d` feat(quick-1-1): fix QUANT-04 — add ingest_games_seasons and --games CLI flag
