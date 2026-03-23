---
phase: 14-prop-integration-gap-closure
plan: "01"
subsystem: graph/agents, prop/arbitrage, graph/state
tags: [gap-closure, prop-integration, wiring, tdd, PROP-01, PROP-06, INFRA-01]
dependency_graph:
  requires: [13-02]
  provides: [PROP-01, PROP-06, INFRA-01]
  affects: [graph/agents, prop/arbitrage, graph/graph, graph/state]
tech_stack:
  added: []
  patterns:
    - module-level imports for mock patchability (OddsAPIPoller, httpx, InjuryWeatherScraper)
    - sport=None auto-detect pattern in closure factory (runtime state key resolution)
    - TypedDict field addition with docstring and type: ignore[misc]
key_files:
  created:
    - tests/test_prop_integration_gap_closure.py
  modified:
    - src/sportsbet/graph/agents.py
    - src/sportsbet/prop/arbitrage.py
    - src/sportsbet/graph/graph.py
    - src/sportsbet/graph/state.py
    - tests/test_prop_pipeline_wiring.py
    - tests/test_context.py
decisions:
  - "Module-level imports of OddsAPIPoller, BudgetExhaustedError, InjuryWeatherScraper, httpx in agents.py — closure-scoped imports cannot be patched via sportsbet.graph.agents.name (extends Phase 8 DATA-03 decision)"
  - "sport=None auto-detect resolves state key at runtime inside closure, not at factory construction time — allows create_graph_with_sqlite to pass a single node that handles both NFL and NBA routes"
  - "prop_filters: dict[str, Any] | None as last field in GraphState — access via state.get('prop_filters') for non-prop routes; INFRA-01 compliance"
  - "test_context.py tests patched to also mock fetch_player_props and write_player_prop_snapshot — Step 1c is now an active code path that must be suppressed in unit tests"
metrics:
  duration: 7min
  completed_date: "2026-03-23"
  tasks_completed: 2
  files_modified: 7
requirements_closed: [PROP-01, PROP-06, INFRA-01]
---

# Phase 14 Plan 01: Prop Integration Gap Closure Summary

**One-liner:** Three v1.0 audit wiring gaps closed — context agent now persists NFL prop snapshots (PROP-01), prop arbitrage agent auto-detects NBA state key (PROP-06), and GraphState TypedDict declares prop_filters (INFRA-01).

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Wave 0: RED test scaffold for all three gaps | 43a0a5a | tests/test_prop_integration_gap_closure.py, tests/test_prop_pipeline_wiring.py |
| 2 | Wave 1: Implement all four source-file fixes | db4d730 | agents.py, arbitrage.py, graph.py, state.py, test_context.py |

## What Was Built

### Gap 1 — PROP-01: context_agent prop snapshot persistence

`src/sportsbet/graph/agents.py` now includes Step 1c: after Step 1b (odds persistence), the context agent calls `OddsAPIPoller.fetch_player_props("nfl")` and iterates through events/bookmakers/markets/outcomes to construct `PlayerPropSnapshotCreate` instances and write them via `write_player_prop_snapshot`. Error handling mirrors the BudgetExhaustedError pattern from Step 1.

Module-level imports added alongside existing pattern:
- `from sportsbet.ingestion.odds_poller import BudgetExhaustedError, OddsAPIPoller`
- `from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, write_player_prop_snapshot`
- `from sportsbet.ingestion.scraper import TEAM_ABBR_TO_ESPN_ID, InjuryWeatherScraper`
- `import httpx`

### Gap 2 — PROP-06: sport=None auto-detect in make_prop_arbitrage_agent

`src/sportsbet/prop/arbitrage.py` signature changed from `sport: str = "nfl"` to `sport: str | None = "nfl"`. Inside the async closure, when `sport is None`, the agent checks `state.get("nba_prop_result")` first; if present, uses it with `resolved_sport="nba"`, otherwise falls back to `state.get("prop_result")` with `resolved_sport="nfl"`. All log calls use `resolved_sport` consistently.

### Gap 3 — graph.py: sport=None at create_graph_with_sqlite

`src/sportsbet/graph/graph.py` line 397 changed from `make_prop_arbitrage_agent(sport="nfl")` to `make_prop_arbitrage_agent(sport=None)` so the runtime factory handles both NFL and NBA routes from a single prop_arbitrage_node.

### Gap 4 — INFRA-01: GraphState prop_filters field

`src/sportsbet/graph/state.py` gained `prop_filters: dict[str, Any] | None  # type: ignore[misc]` after `prop_line`, with docstring entry explaining its role as optional filter context for PropQueryBuilder/NBAQueryBuilder.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Module-level imports required for mock patchability**
- **Found during:** Task 2 — first GREEN run of test_context_agent_calls_write_player_prop_snapshot
- **Issue:** `OddsAPIPoller`, `httpx`, `InjuryWeatherScraper` were closure-scoped imports; `patch("sportsbet.graph.agents.OddsAPIPoller")` raised `AttributeError: module does not have the attribute 'OddsAPIPoller'`
- **Fix:** Moved all four imports to module level in agents.py
- **Files modified:** src/sportsbet/graph/agents.py
- **Commit:** db4d730

**2. [Rule 1 - Bug] test_context.py tests broke due to Step 1c activation**
- **Found during:** Full suite run after Task 2
- **Issue:** `test_context_agent_updates_graphstate` and `test_downstream_reads_state` patched `fetch_nfl_odds` but not `fetch_player_props`; Step 1c now calls `fetch_player_props` which triggered real HTTP calls through mocked httpx client, causing `mock_client_instance.get.assert_not_called()` to fail
- **Fix:** Added `patch.object(OddsAPIPoller, "fetch_player_props", return_value=[])` and `patch("sportsbet.graph.agents.write_player_prop_snapshot")` to both tests
- **Files modified:** tests/test_context.py
- **Commit:** db4d730

## Verification Results

```
pytest tests/test_prop_integration_gap_closure.py -v
3 passed in 0.18s

pytest tests/test_prop_pipeline_wiring.py -v
7 passed in 0.12s

pytest tests/ -x
156 passed, 11 skipped, 0 failures in 43.73s
```

- `"prop_filters" in GraphState.__annotations__` — True (confirmed by test_graphstate_declares_prop_filters PASSED)
- `grep "write_player_prop_snapshot" src/sportsbet/graph/agents.py` — returns module-level import line
- `grep "sport=None" src/sportsbet/graph/graph.py` — returns prop_arbitrage_node line

## Self-Check: PASSED

- FOUND: .planning/phases/14-prop-integration-gap-closure/14-01-SUMMARY.md
- FOUND: tests/test_prop_integration_gap_closure.py
- FOUND: commit 43a0a5a (test RED scaffold)
- FOUND: commit db4d730 (implementation)
