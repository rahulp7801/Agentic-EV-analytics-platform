---
phase: 04-context-and-odds-ingestion
plan: "04"
subsystem: agent
tags: [langgraph, pydantic, asyncpg, httpx, odds-api, espn-api, context-agent, tdd]

# Dependency graph
requires:
  - phase: 04-02
    provides: OddsAPIPoller with BudgetExhaustedError, is_stale(), fetch_nfl_odds()
  - phase: 04-03
    provides: InjuryWeatherScraper with fetch_team_injuries(), write_injury_reports(), TEAM_ABBR_TO_ESPN_ID
  - phase: 04-01
    provides: ContextSignals model, AgentOddsSnapshot model, GraphState.context_signals field
provides:
  - make_context_agent(pool, api_key, daily_credit_cap) closure factory in agents.py
  - _extract_odds_snapshot() American odds -> Decimal implied_probability conversion
  - create_graph(context_node=...) optional parameter for real context agent wiring
  - create_graph_with_sqlite(api_key=..., daily_credit_cap=...) runtime factory update
affects:
  - phase-05-arbitrage-agent (reads context_signals from state, never re-fetches)
  - phase-06-kinematic-agent (same context_signals contract)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Closure factory pattern for async LangGraph nodes (make_context_agent mirrors make_quant_agent)"
    - "BudgetExhaustedError caught inside closure — graceful degradation to odds_snapshot=None"
    - "patch.object on OddsAPIPoller.fetch_nfl_odds for method-level mocking of async context manager internals"

key-files:
  created: []
  modified:
    - src/sportsbet/graph/agents.py
    - src/sportsbet/graph/graph.py
    - tests/test_context.py

key-decisions:
  - "make_context_agent closure factory pattern mirrors make_quant_agent — pool, api_key, daily_credit_cap injected at construction time; sync stub context_agent preserved for backward-compat when context_node=None"
  - "BudgetExhaustedError caught inside closure returning ContextSignals with odds_snapshot=None — never propagates exception to LangGraph state machine"
  - "_extract_odds_snapshot uses Decimal(str(round(raw_prob, 6))) for American odds conversion — prevents float assigned to Decimal field in strict Pydantic model"
  - "Only Out and Questionable injury statuses added to injury_flags — Probable/Doubtful omitted for signal clarity"
  - "weather_json=None deferred to v2 — keeps v1 Context Agent testable without Playwright/NFLWeather"

patterns-established:
  - "Agent closure factory: all production async agents use closure pattern (pool + external deps injected at construction)"
  - "Stub fallback pattern: create_graph(context_node=None) always works without real credentials — enables isolated testing"
  - "Partial state dict return: context_agent returns {'context_signals': ContextSignals(...)} — LangGraph merges via reducers"

requirements-completed: [CTXT-04]

# Metrics
duration: 3min
completed: 2026-03-15
---

# Phase 4 Plan 04: Context Agent Closure Factory Summary

**make_context_agent(pool, api_key, daily_credit_cap) closure factory wiring live OddsAPIPoller + InjuryWeatherScraper into a ContextSignals partial state dict, completing the Phase 4 pipeline**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-15T03:39:34Z
- **Completed:** 2026-03-15T03:43:00Z
- **Tasks:** 2 (TDD: RED then GREEN)
- **Files modified:** 3

## Accomplishments

- Implemented `make_context_agent(pool, api_key, daily_credit_cap)` closure factory in agents.py — async LangGraph-compatible node that fetches live NFL odds via OddsAPIPoller, parses injuries via InjuryWeatherScraper, assembles ContextSignals, and returns a partial state dict
- Added `_extract_odds_snapshot()` helper that converts American odds integers to Decimal implied_probability at ingestion time, returning None gracefully on empty or malformed odds data
- Updated `create_graph()` to accept optional `context_node` parameter with stub fallback for full backward-compatibility; updated `create_graph_with_sqlite()` to accept `api_key` and `daily_credit_cap` for runtime wiring
- All 8 Phase 4 tests green (CTXT-01 through CTXT-04); full suite 59 passed, 9 skipped, 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Write RED tests for CTXT-04** - `ecf7693` (test)
2. **Task 2: Implement make_context_agent and graph wiring** - `999c37d` (feat)

**Plan metadata:** TBD (docs commit below)

_Note: TDD tasks have two commits (RED test stub -> GREEN implementation)_

## Files Created/Modified

- `src/sportsbet/graph/agents.py` - Added make_context_agent closure factory and _extract_odds_snapshot helper; updated module docstring for Phase 4
- `src/sportsbet/graph/graph.py` - Added context_node parameter to create_graph() and api_key/daily_credit_cap to create_graph_with_sqlite(); updated module docstring
- `tests/test_context.py` - Replaced 2 pytest.fail() CTXT-04 stubs with real test implementations covering both unit and integration scenarios

## Decisions Made

- `make_context_agent` closure pattern mirrors `make_quant_agent` exactly — consistent factory convention across all production agents
- `BudgetExhaustedError` caught inside closure with graceful degradation — downstream agents receive `ContextSignals(odds_snapshot=None)` rather than exception propagation
- `_extract_odds_snapshot` uses `Decimal(str(round(raw_prob, 6)))` wrapping — prevents float-to-Decimal assignment error in strict Pydantic `AgentOddsSnapshot` model
- Only `Out` and `Questionable` injury statuses surfaced in `injury_flags` — `Probable`/`Doubtful` excluded for signal clarity
- `weather_json=None` kept as v2 deferral — avoids Playwright dependency in v1 while keeping the scraper interface clean

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - both TDD phases (RED and GREEN) executed cleanly on first attempt. The mock patch strategy for `OddsAPIPoller.fetch_nfl_odds` using `patch.object` on the imported class worked correctly alongside the `httpx.AsyncClient` patch for the injury scraper path.

## Next Phase Readiness

- Phase 4 pipeline is complete: OddsAPIPoller (Plan 02) + InjuryWeatherScraper (Plan 03) + make_context_agent (Plan 04) are all integrated and tested
- `GraphState.context_signals` is now populated by the real context agent for any `request_type="context_update"` graph invocation
- Phase 5 (Arbitrage Agent) can safely read `state["context_signals"].odds_snapshot` without re-fetching the Odds API
- Remaining Phase 4 concern (pre-existing blocker): verify current Odds API sport key naming against live documentation before production deployment

---
*Phase: 04-context-and-odds-ingestion*
*Completed: 2026-03-15*
