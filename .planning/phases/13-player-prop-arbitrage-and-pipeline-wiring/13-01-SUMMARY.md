---
phase: 13-player-prop-arbitrage-and-pipeline-wiring
plan: "01"
subsystem: prop-arbitrage
tags: [prop, arbitrage, kelly, ev, correlation-guard, langgraph, tdd]
dependency_graph:
  requires:
    - src/sportsbet/arbitrage/ev.py          # compute_ev_percentage, build_trade_plan
    - src/sportsbet/arbitrage/kelly.py       # fractional_kelly
    - src/sportsbet/graph/models.py          # EVSignal, PropResult, ContextSignals
    - src/sportsbet/config.py                # settings.max_kelly_fraction
  provides:
    - src/sportsbet/prop/arbitrage.py        # make_prop_arbitrage_agent
    - src/sportsbet/arbitrage/correlation_guard.py  # CONFLICT_PAIRS with 10 pairs
    - src/sportsbet/graph/state.py           # GraphState.prop_type, GraphState.prop_line
  affects:
    - Any LangGraph graph that consumes GraphState (prop_type/prop_line now formally declared)
    - CorrelationGuard callers (10 conflict pairs vs previous 4)
tech_stack:
  added: []
  patterns:
    - TDD red-green cycle (test stubs committed before implementation)
    - Closure factory pattern matching make_arbitrage_agent (Phase 5)
    - Decimal(str(cfg.max_kelly_fraction)) for Kelly sizing — locked Phase 2 pattern
    - frozenset[frozenset[str]] for O(1) conflict pair membership testing
key_files:
  created:
    - src/sportsbet/prop/arbitrage.py
    - tests/test_prop_arbitrage.py
  modified:
    - src/sportsbet/arbitrage/correlation_guard.py
    - src/sportsbet/graph/state.py
decisions:
  - "[Phase 13-01]: make_prop_arbitrage_agent closure factory: sport param selects state key (prop_result vs nba_prop_result) — single factory covers both NFL and NBA prop routes"
  - "[Phase 13-01]: _build_prop_trade_plan adds sample_size and mean_stat to Bullet 2 — prop-specific context vs generic build_trade_plan"
  - "[Phase 13-01]: EVSignal reused for prop markets — no new Pydantic model (RESEARCH.md anti-pattern note honored)"
  - "[Phase 13-01]: CONFLICT_PAIRS extended to 10 entries (4 Phase 5 + 6 Phase 13); CorrelationGuard class body unchanged — open/closed principle"
  - "[Phase 13-01]: prop_type: str and prop_line: Any added as required GraphState fields — resolves Pitfall 5 open question from RESEARCH.md; non-prop routes access via state.get()"
metrics:
  duration: 4 min
  completed_date: "2026-03-23"
  tasks_completed: 2
  files_created: 2
  files_modified: 2
---

# Phase 13 Plan 01: PropArbitrageAgent and CorrelationGuard Extension Summary

**One-liner:** PropArbitrageAgent closure factory with fractional Kelly + 3-bullet trade plan for NFL/NBA prop markets, plus CorrelationGuard CONFLICT_PAIRS extended to 10 prop-aware pairs.

## What Was Built

### Task 1: TDD Red — Test Stubs (PROP-06, PROP-07)

Created `tests/test_prop_arbitrage.py` with 10 failing tests organized in 3 classes:
- `TestProp06EVSignalProduced` (5 tests): +EV signal production, Kelly bounds, -EV suppression, trade plan length, missing prop_result guard
- `TestProp07CorrelationGuard` (3 tests): prop-to-prop conflict blocking, CONFLICT_PAIRS membership, single-signal pass-through
- `TestE2EPropPipeline` (2 tests): NFL and NBA end-to-end integration using direct agent invocation

Import guard wraps `make_prop_arbitrage_agent` in try/except so the file is importable before the implementation exists. Tests fail with `AssertionError: make_prop_arbitrage_agent not importable yet` rather than SyntaxError.

### Task 2: TDD Green — Implementation

**`src/sportsbet/prop/arbitrage.py`:**
- `make_prop_arbitrage_agent(settings_override=None, sport="nfl")` closure factory
- sport param selects `prop_result` (NFL) or `nba_prop_result` (NBA) from state
- Guards: missing prop_result, missing true_probability, missing context_signals, missing odds_snapshot, zero EV — all return `{"ev_signal": None}`
- `_build_prop_trade_plan`: Bullet 1 = EV edge on market, Bullet 2 = Kelly sizing with sample_size/mean_stat, Bullet 3 = injury flags or clean bill
- Returns `{"ev_signal": EVSignal, "pending_signals": [signal]}` for +EV cases
- Structlog instrumentation at entry, no-signal exits, and signal-produced path

**`src/sportsbet/arbitrage/correlation_guard.py`:**
- CONFLICT_PAIRS extended from 4 to 10 entries
- 6 new Phase 13 prop pairs with inline comments:
  - `{over_pass_yds, under_rec_yds}` — PROP-07 explicit
  - `{under_pass_yds, over_rec_yds}` — inverse
  - `{over_pass_tds, under_rec_tds}` — TD correlation
  - `{under_pass_tds, over_rec_tds}` — inverse
  - `{over_pass_yds, under_total_points}` — prop-to-game-total
  - `{over_rush_yds, under_total_points}` — prop-to-game-total
- CorrelationGuard class body unchanged

**`src/sportsbet/graph/state.py`:**
- `prop_type: str` — prop market type identifier (Phase 13, PROP-06)
- `prop_line: Any` — numeric/string prop line value (Phase 13, PROP-06)
- Docstring updated with descriptions for both new fields
- Resolves Pitfall 5 open question from RESEARCH.md

## Verification Results

```
python -m pytest tests/test_prop_arbitrage.py -q   →  10 passed
python -m pytest tests/ -x -q                       →  146 passed, 11 skipped
CONFLICT_PAIRS count                                 →  10
make_prop_arbitrage_agent importable                 →  ok
'prop_type' in GraphState.__annotations__            →  True
'prop_line' in GraphState.__annotations__            →  True
```

## Deviations from Plan

None — plan executed exactly as written. Both TDD phases (red/green) completed per spec with all must_have truths and artifacts satisfied.

## Commits

| Hash    | Type | Description                                                      |
| ------- | ---- | ---------------------------------------------------------------- |
| 817cced | test | add failing test stubs for PROP-06 and PROP-07                   |
| acdf811 | feat | implement PropArbitrageAgent, extend CorrelationGuard, add GraphState fields |

## Self-Check: PASSED

- [x] `src/sportsbet/prop/arbitrage.py` — created, make_prop_arbitrage_agent exported
- [x] `tests/test_prop_arbitrage.py` — created, 10 tests, min_lines 80 satisfied (274 lines)
- [x] `src/sportsbet/arbitrage/correlation_guard.py` — CONFLICT_PAIRS has 10 entries
- [x] `src/sportsbet/graph/state.py` — prop_type and prop_line declared
- [x] commits 817cced and acdf811 exist in git log
- [x] Full test suite: 146 passed, 11 skipped, 0 failures
