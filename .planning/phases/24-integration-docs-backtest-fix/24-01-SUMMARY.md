---
phase: 24-integration-docs-backtest-fix
plan: "01"
subsystem: graph-docs-and-backtest-fix
tags: [documentation, backtest, null-guard, multi-invocation, sql-fix]
dependency_graph:
  requires: []
  provides:
    - ARBT-01 two-invocation comment block in graph.py
    - CTXT-04/PROP-04 Invocation ordering docstrings in prop agents
    - QUANT-04 NULL game_id WHERE guard in load_snapshots
    - QUANT-04 game_start_time None skip in build_signals
    - test_null_game_id_row_not_silently_dropped test
  affects:
    - src/sportsbet/graph/graph.py
    - src/sportsbet/prop/agents.py
    - src/sportsbet/prop/nba_agents.py
    - src/sportsbet/quant/backtest_replay.py
    - tests/test_backtest_pipeline.py
tech_stack:
  added: []
  patterns:
    - SQL WHERE guard before LEFT JOIN timestamp arithmetic
    - Python-layer defensive None guard parallel to price skip pattern
    - TDD red-green for QUANT-04 NULL row handling
key_files:
  created: []
  modified:
    - src/sportsbet/graph/graph.py
    - src/sportsbet/prop/agents.py
    - src/sportsbet/prop/nba_agents.py
    - src/sportsbet/quant/backtest_replay.py
    - tests/test_backtest_pipeline.py
decisions:
  - "ARBT-01 comment block placed immediately after add_edge('quant_agent', END) — co-located with node for API consumer visibility, mirrors existing PROP-04 kinematic block placement pattern"
  - "game_start_time accessed via row.get() with None guard before use — defensive layer parallel to existing price is None skip, prevents silent TypeError for any NULL rows bypassing SQL guard"
  - "o.game_id IS NOT NULL as first WHERE clause in load_snapshots — placed before timestamp arithmetic clause so NULL game_id rows are excluded before LEFT JOIN NULL evaluation"
metrics:
  duration: 4 minutes
  completed_date: "2026-03-27"
  tasks_completed: 2
  files_modified: 5
---

# Phase 24 Plan 01: Integration Documentation and Backtest Fix Summary

**One-liner:** ARBT-01/PROP-04 multi-invocation checkpoint docs and QUANT-04 SQL NULL game_id guard with Python defensive skip in backtest pipeline.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Document ARBT-01 and CTXT-04/PROP-04 multi-invocation patterns | 43b7b91 | graph.py, prop/agents.py, prop/nba_agents.py |
| 2 (RED) | Add failing test for QUANT-04 NULL game_id handling | ccf608e | tests/test_backtest_pipeline.py |
| 2 (GREEN) | Fix load_snapshots NULL game_id drop and build_signals guard | 34e2570 | backtest_replay.py |

## What Was Built

### Task 1: Multi-Invocation Checkpoint Documentation

Three documentation-only edits to close audit gaps for implemented-but-undocumented patterns:

**graph.py — ARBT-01 comment block (lines 302-317):** Inserted immediately after `builder.add_edge("quant_agent", END)`, describing the quant_analysis -> arbitrage_analysis two-invocation requirement. Documents that both invocations must use the same thread_id and that arbitrage_agent returns ev_signal=None (Guard 1) when quant_result is absent from checkpoint. Mirrors the existing PROP-04 kinematic boost comment block placement pattern.

**prop/agents.py — Invocation ordering section in make_prop_quant_agent docstring (line 130):** Documents that context_update must precede prop_analysis in the same thread_id for situational_params (injury-adjusted queries). Clarifies the correct production fallback: situational_params=None falls back to {} (empty dict), resulting in teammate_out=None in PropParams and the query runs without injury-adjusted WHERE clauses.

**prop/nba_agents.py — Invocation ordering section in make_nba_quant_agent docstring (line 158):** Documents that the graph auto-inserts nba_context_producer before nba_quant_agent (nba_context_producer -> nba_quant_agent edge). Callers using request_type="nba_prop_analysis" do not need a separate context invocation. Clarifies the nba_context_signals=None fallback behavior.

### Task 2: QUANT-04 NULL game_id Fix (TDD)

**SQL layer guard (load_snapshots WHERE clause):** Added `"o.game_id IS NOT NULL"` as the first entry in `where_clauses`. This prevents odds_snapshot rows with no matching game from reaching Python via LEFT JOIN timestamp arithmetic — when game_id is NULL the JOIN produces no match, making the timestamp clause evaluate to NULL (which fails the WHERE predicate silently rather than filtering correctly).

**Python layer guard (build_signals):** Added `game_start_time is None` skip immediately after the existing `price is None` skip. Follows the exact same pattern: `row.get("game_start_time")`, None check, `logger.debug("skipping_row_no_game_start_time", ...)`, `continue`. Also refactored the `game_start_time` variable from direct key access (`row["game_start_time"]`) to `.get()` for consistency.

**New test:** `test_null_game_id_row_not_silently_dropped` uses `FIXTURE_ROW_NULL_GAME` (game_id=None, game_start_time=None) and asserts `build_signals([FIXTURE_ROW_NULL_GAME]) == []`. Verifies explicit Python-layer handling rather than silent exclusion or TypeError.

## Verification

```
grep -n "ARBT-01" src/sportsbet/graph/graph.py
302:    # ARBT-01 quant->arbitrage two-invocation checkpoint pattern.

grep -n "Invocation ordering" src/sportsbet/prop/agents.py src/sportsbet/prop/nba_agents.py
src/sportsbet/prop/agents.py:130:    Invocation ordering (CTXT-04/PROP-04):
src/sportsbet/prop/nba_agents.py:158:    Invocation ordering (CTXT-04/PROP-04):

grep -n "game_id IS NOT NULL" src/sportsbet/quant/backtest_replay.py
159:        "o.game_id IS NOT NULL", ...

grep -n "game_start_time is None" src/sportsbet/quant/backtest_replay.py
101:        if game_start_time is None:

pytest tests/ -x -q
215 passed, 11 skipped, 2 xfailed, 4 warnings
```

All success criteria met. Full suite green (214 → 215 passing, +1 new test).

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- [x] src/sportsbet/graph/graph.py contains "ARBT-01" at line 302 after add_edge("quant_agent", END)
- [x] src/sportsbet/prop/agents.py contains "Invocation ordering" at line 130
- [x] src/sportsbet/prop/nba_agents.py contains "Invocation ordering" at line 158
- [x] src/sportsbet/quant/backtest_replay.py contains "game_id IS NOT NULL" at line 159
- [x] src/sportsbet/quant/backtest_replay.py contains "game_start_time is None" at line 101
- [x] tests/test_backtest_pipeline.py contains test_null_game_id_row_not_silently_dropped
- [x] Commits 43b7b91, ccf608e, 34e2570 exist in git log
- [x] 215 passed, 11 skipped, 2 xfailed
