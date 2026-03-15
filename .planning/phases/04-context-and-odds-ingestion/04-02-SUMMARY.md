---
phase: 04-context-and-odds-ingestion
plan: "02"
subsystem: ingestion
tags: [httpx, odds-api, async, pydantic, tdd, budget-guard, staleness]

requires:
  - phase: 04-01
    provides: InjuryReport ORM, ContextSignals Pydantic model, GraphState extension
  - phase: 03-quant-engine
    provides: American odds to implied probability conversion pattern

provides:
  - OddsAPIPoller async context manager (httpx-based) with budget guard
  - BudgetExhaustedError raised when x-requests-remaining < 1 without HTTP call
  - is_stale() timezone-aware staleness guard for AgentOddsSnapshot freshness
  - NFL_SPORT_KEY = "americanfootball_nfl" module constant
  - 4 green TDD tests for CTXT-01 and CTXT-02 with fully mocked HTTP

affects:
  - 04-03: Context agent pipeline will call OddsAPIPoller.fetch_nfl_odds()
  - 05-arbitrage: Arbitrage Agent consumes OddsAPIPoller output; is_stale() gates stale odds
  - phase-06: Any live odds feed depends on OddsAPIPoller budget tracking

tech-stack:
  added: [httpx (async HTTP client, from site-packages)]
  patterns:
    - OddsAPIPoller uses async context manager protocol with __aenter__/__aexit__
    - httpx.AsyncClient entered via __aenter__() inside OddsAPIPoller so unittest.mock.patch works
    - Budget guard fires before any HTTP call when _credits_remaining is not None and < 1
    - Warning logged on first __aenter__ when _credits_remaining is None (counter reset on restart)
    - is_stale() uses datetime.now(timezone.utc) exclusively — utcnow() is forbidden

key-files:
  created:
    - src/sportsbet/ingestion/odds_poller.py
    - tests/test_context.py
  modified: []

key-decisions:
  - "httpx.AsyncClient entered via internal __aenter__() call inside OddsAPIPoller so patch('sportsbet.ingestion.odds_poller.httpx.AsyncClient') correctly intercepts the client instance"
  - "_credits_remaining persisted in-memory only in v1 — WARNING logged on restart; persistent budget tracking deferred to Phase 5 per RESEARCH.md open question #3"
  - "is_stale() raises TypeError on naive datetime input — enforces timezone-awareness at the API boundary"

patterns-established:
  - "Odds API mocking: patch httpx.AsyncClient at module level, set __aenter__ returning AsyncMock client, mock .get() and .headers and .raise_for_status()"
  - "Budget guard pattern: check _credits_remaining before any I/O operation — fail fast, no wasted credits"

requirements-completed: [CTXT-01, CTXT-02]

duration: 12min
completed: 2026-03-15
---

# Phase 4 Plan 02: Odds API Poller Summary

**httpx-based OddsAPIPoller async context manager with pre-flight budget guard and timezone-aware is_stale() staleness gate — 4 TDD green tests, zero live API credits consumed**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-15T03:27:46Z
- **Completed:** 2026-03-15T03:39:46Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 2

## Accomplishments

- OddsAPIPoller async context manager wraps httpx.AsyncClient; fetch_nfl_odds() returns parsed JSON list and updates _credits_remaining from x-requests-remaining header
- BudgetExhaustedError raised immediately when _credits_remaining < 1 — no HTTP call dispatched; verified by mock.assert_not_called()
- is_stale() function uses datetime.now(timezone.utc) exclusively (utcnow() absent from codebase); returns True/False based on configurable threshold

## Task Commits

Each task was committed atomically:

1. **Task 1: Write RED tests for CTXT-01 and CTXT-02** - `93037da` (test)
2. **Task 2: Implement odds_poller.py (GREEN phase)** - `5e4e9f0` (feat)

## Files Created/Modified

- `src/sportsbet/ingestion/odds_poller.py` - OddsAPIPoller, BudgetExhaustedError, is_stale(), NFL_SPORT_KEY, ODDS_API_BASE, DEFAULT_STALENESS_MINUTES
- `tests/test_context.py` - 4 CTXT-01/02 tests (green) + 4 CTXT-03/04 stubs (pytest.fail, expected failures)

## Decisions Made

- Used `httpx.AsyncClient.__aenter__()` internally inside OddsAPIPoller.__aenter__ so `patch("sportsbet.ingestion.odds_poller.httpx.AsyncClient")` intercepts the correct client object — necessary for unittest.mock pattern without respx dependency
- _credits_remaining is in-memory only in v1; structlog WARNING logged on startup when counter is None (reset signal); persistent tracking deferred per RESEARCH.md
- is_stale() raises TypeError on naive datetime to enforce UTC-awareness at the API boundary — fail loudly rather than silently computing wrong age

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed async context manager implementation to match mock pattern**
- **Found during:** Task 2 (GREEN phase first run)
- **Issue:** Initial implementation called `await self._client.__aenter__()` after assigning `self._client = httpx.AsyncClient(...)`, but `__aexit__` called `await self._client.aclose()`. The mock had `__aenter__` returning `mock_client` (AsyncMock) but `aclose` on the raw mock was not awaitable.
- **Fix:** Changed to store both `_client_cm` (the context manager object) and `_client` (the entered client); `__aexit__` delegates to `_client_cm.__aexit__()`. This matches the mock setup where `mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)`.
- **Files modified:** src/sportsbet/ingestion/odds_poller.py
- **Verification:** All 4 CTXT-01/02 tests pass after fix
- **Committed in:** 5e4e9f0 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in async context manager delegation)
**Impact on plan:** Fix required for tests to pass; no scope change; implementation semantics unchanged.

## Issues Encountered

- Pre-existing failure in `tests/test_graph.py::TestGraphState::test_graphstate_has_required_fields` (NameError: 'ContextSignals' is not defined). Confirmed pre-existing before this plan's changes — not caused by odds_poller.py. Logged as out-of-scope; deferred.

## User Setup Required

None - no external service configuration required. Live Odds API calls are mocked in all tests.

## Next Phase Readiness

- OddsAPIPoller ready for consumption by Phase 4 Plan 03 (Context Agent RSS/scraper pipeline)
- is_stale() gate is available for Arbitrage Agent to reject stale snapshots before +EV comparison
- CTXT-03 and CTXT-04 test stubs present in tests/test_context.py awaiting Plan 03 implementation
- Pre-existing test_graph.py failure should be resolved before Phase 4 Plan 03 to clean up suite

---
*Phase: 04-context-and-odds-ingestion*
*Completed: 2026-03-15*
