---
phase: 04-context-and-odds-ingestion
plan: "03"
subsystem: ingestion
tags: [espn-api, asyncpg, httpx, structlog, injury-data, tdd]

requires:
  - phase: 04-01-context-and-odds-ingestion
    provides: InjuryReport ORM model in db/models.py; ContextSignals Pydantic model; GraphState.context_signals field
  - phase: 01-data-foundation
    provides: asyncpg pool pattern and injury_reports table schema

provides:
  - InjuryWeatherScraper class with ESPN Core API integration
  - TEAM_ABBR_TO_ESPN_ID mapping for all 32 NFL teams
  - parse_espn_injury_item() with "Unknown" fallback for schema drift tolerance
  - 2 CTXT-03 passing tests (test_espn_injury_parsing, test_scraper_writes_injury_report)

affects:
  - 04-04-context-and-odds-ingestion (context agent uses InjuryWeatherScraper to populate GraphState.context_signals)

tech-stack:
  added: []
  patterns:
    - "ESPN Core API numeric team IDs mapped via TEAM_ABBR_TO_ESPN_ID static dict"
    - ".get() with 'Unknown' fallback at every level for undocumented API schema tolerance"
    - "asyncpg $N positional params in INSERT — no f-strings in SQL"
    - "scraped_at omitted from INSERT — relies on server_default=now()"
    - "httpx.AsyncClient injected at construction time for testability"

key-files:
  created:
    - src/sportsbet/ingestion/scraper.py
  modified:
    - tests/test_context.py
    - src/sportsbet/graph/state.py

key-decisions:
  - "MagicMock (not AsyncMock) for pool.acquire in test — AsyncMock makes acquire() return a coroutine which breaks async with pool.acquire() as conn pattern"
  - "ContextSignals imported at runtime in state.py (not TYPE_CHECKING) — LangGraph calls get_type_hints(GraphState) which cannot resolve forward refs for TYPE_CHECKING-only imports"
  - "Weather scraping (Playwright/NFLWeather.com) deferred to v2 — Context Agent accepts weather_json=None in v1; keeps scraper.py focused and testable"
  - "parse_espn_injury_item() as standalone function, not class method — allows direct import and unit testing without instantiating InjuryWeatherScraper"

patterns-established:
  - "Standalone parser function + class writer: parse_espn_injury_item() is pure/testable; InjuryWeatherScraper handles I/O"
  - "structlog WARNING on schema drift: log.warning('espn_injury_schema_drift') when displayName missing — machine-readable signal for monitoring"

requirements-completed: [CTXT-03]

duration: 15min
completed: "2026-03-15"
---

# Phase 4 Plan 03: InjuryWeatherScraper Summary

**ESPN Core API injury scraper with asyncpg writer: parse_espn_injury_item() with "Unknown" fallbacks + InjuryWeatherScraper writing to injury_reports via $N positional params**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-15T03:20:00Z
- **Completed:** 2026-03-15T03:36:48Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 3

## Accomplishments

- Implemented `scraper.py` with `InjuryWeatherScraper`, `TEAM_ABBR_TO_ESPN_ID` (32 NFL teams), `parse_espn_injury_item()`, and `ESPN_INJURIES_URL`
- All ESPN fields use `.get()` with "Unknown" fallback — zero KeyError risk on schema drift
- CTXT-03 TDD tests GREEN: `test_espn_injury_parsing` and `test_scraper_writes_injury_report` both pass
- Fixed pre-existing bug: `state.py` imported `ContextSignals` under `TYPE_CHECKING`, causing LangGraph's `get_type_hints(GraphState)` to raise `NameError` — moved to runtime import

## Task Commits

1. **Task 1: Write RED tests for CTXT-03** - `2adb2a6` (test)
2. **Task 2: Implement scraper.py GREEN phase** - `b426511` (feat)

## Files Created/Modified

- `src/sportsbet/ingestion/scraper.py` - InjuryWeatherScraper class, TEAM_ABBR_TO_ESPN_ID (32 entries), parse_espn_injury_item(), ESPN_INJURIES_URL
- `tests/test_context.py` - CTXT-03 tests added: test_espn_injury_parsing, test_scraper_writes_injury_report; CTXT-04 stubs (pytest.fail) for Plan 04-04
- `src/sportsbet/graph/state.py` - ContextSignals import moved from TYPE_CHECKING to runtime import; Optional[ContextSignals] annotation for context_signals field

## Decisions Made

- **MagicMock for pool.acquire**: The plan spec used `AsyncMock` for `mock_pool`, but `AsyncMock` makes `pool.acquire()` return a coroutine, which breaks `async with pool.acquire() as conn`. Changed to `MagicMock` for `mock_pool` so `acquire.return_value` is returned synchronously as an async context manager.
- **Runtime ContextSignals import**: `state.py` had `ContextSignals` under `TYPE_CHECKING`. LangGraph calls `get_type_hints(GraphState)` at graph compilation, which can't resolve TYPE_CHECKING-only imports → `NameError`. Fixed by importing at runtime. This was a pre-existing bug introduced in Plan 04-01 foundations.
- **Weather scraping deferred**: Playwright-based weather scraping not included in v1. Context Agent accepts `weather_json=None` for all games. Keeps `scraper.py` focused and testable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ContextSignals TYPE_CHECKING import broke LangGraph graph compilation**
- **Found during:** Task 1 (running pre-existing test suite before writing RED tests)
- **Issue:** `state.py` imported `ContextSignals` under `if TYPE_CHECKING:` guard with string annotation `"ContextSignals | None"`. LangGraph calls `get_type_hints(GraphState, include_extras=True)` at `StateGraph(GraphState)` construction, which tries to resolve the forward reference. Since `ContextSignals` is not in global namespace at runtime, this raises `NameError`, causing 9 test failures in `test_graph.py`.
- **Fix:** Moved `from sportsbet.graph.models import ContextSignals` to a regular runtime import; changed annotation from `"ContextSignals | None"` to `Optional[ContextSignals]`.
- **Files modified:** `src/sportsbet/graph/state.py`
- **Verification:** `python -m pytest tests/test_graph.py -q` — 13 passed (0 failures, restored from 9 failures).
- **Committed in:** b426511 (included in Task 2 commit)

**2. [Rule 1 - Bug] AsyncMock for pool.acquire incompatible with async with pattern**
- **Found during:** Task 2 (GREEN implementation, first test run)
- **Issue:** `mock_pool = AsyncMock()` makes `pool.acquire` an AsyncMock child. Calling `pool.acquire()` returns a coroutine. `async with pool.acquire() as conn` fails with `TypeError: 'coroutine' object does not support the asynchronous context manager protocol`.
- **Fix:** Changed `mock_pool = AsyncMock()` to `mock_pool = MagicMock()` in `test_scraper_writes_injury_report` so `pool.acquire()` returns `mock_pool.acquire.return_value` synchronously as an async CM.
- **Files modified:** `tests/test_context.py`
- **Verification:** Both CTXT-03 tests GREEN after fix.
- **Committed in:** b426511 (part of Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs)
**Impact on plan:** Both fixes essential for correctness. No scope creep.

## Issues Encountered

None beyond the two auto-fixed bugs documented above.

## Next Phase Readiness

- `scraper.py` ready for Plan 04-04 `make_context_agent` to use
- `InjuryWeatherScraper.fetch_team_injuries()` provides parsed injury dicts; Context Agent will translate to `injury_flags: dict[str, str]` for GraphState
- CTXT-04 stubs (`test_context_agent_updates_graphstate`, `test_downstream_reads_state`) remain as pytest.fail() for Plan 04-04 to implement

---
*Phase: 04-context-and-odds-ingestion*
*Completed: 2026-03-15*
