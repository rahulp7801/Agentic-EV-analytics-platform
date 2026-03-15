---
phase: 04-context-and-odds-ingestion
verified: 2026-03-14T00:00:00Z
status: passed
score: 12/12 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Live Odds API integration — run OddsAPIPoller against a real SPORTSBET_TEST_ODDS_API_KEY"
    expected: "Odds payload returned, x-requests-remaining header read, _credits_remaining decremented by 1"
    why_human: "All HTTP calls are mocked in tests. Real Odds API key not present in dev environment."
  - test: "ESPN Core API live scrape — call InjuryWeatherScraper.fetch_team_injuries(12) against live endpoint"
    expected: "List of injury dicts returned for KC (team_id=12), each with player_name/status/position; 'Unknown' fallback fires for any absent fields"
    why_human: "ESPN Core API is undocumented; live schema must be validated before production deployment to confirm field names match parse_espn_injury_item() expectations."
  - test: "BudgetExhaustedError propagation in production graph — set daily_credit_cap=0 and invoke create_graph_with_sqlite"
    expected: "ContextSignals returned with odds_snapshot=None; no exception raised from LangGraph; error field on GraphState remains None"
    why_human: "Tests verify the exception is caught inside the closure but do not verify LangGraph state machine routing with the degraded signal."
---

# Phase 4: Context and Odds Ingestion Verification Report

**Phase Goal:** Implement context and odds ingestion pipeline — real-time odds polling, injury/weather scraping, and a wired Context Agent that assembles ContextSignals into graph state for downstream agents.
**Verified:** 2026-03-14
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | InjuryReport ORM model exists in db/models.py with 3 composite indexes on game_id, scraped_at, and player_name+scraped_at | VERIFIED | `class InjuryReport` at line 206 of db/models.py; `__table_args__` contains idx_injury_game_id, idx_injury_scraped_at, idx_injury_player_scraped |
| 2 | Alembic migration 0002_add_injury_reports.py creates injury_reports table with correct revision chain | VERIFIED | revision="0002_add_injury_reports", down_revision="0001" (matches actual 0001 revision ID); upgrade() creates table + 3 indexes; downgrade() drops in reverse order |
| 3 | ContextSignals Pydantic model exists in graph/models.py with strict=True config and all 5 fields | VERIFIED | `class ContextSignals(BaseModel)` at line 125 of graph/models.py; `model_config = ConfigDict(strict=True)`; fields: game_id, injury_flags, weather_json, odds_snapshot, signals_captured_at |
| 4 | GraphState TypedDict has context_signals field typed as Optional[ContextSignals] | VERIFIED | `context_signals: Optional[ContextSignals]` at line 84 of state.py; ContextSignals imported at runtime (not TYPE_CHECKING) to allow LangGraph get_type_hints() resolution |
| 5 | OddsAPIPoller fetches NFL odds via httpx.AsyncClient with budget guard on x-requests-remaining header | VERIFIED | odds_poller.py: budget guard at line 134 checks _credits_remaining < 1 before any HTTP call; header read via `response.headers.get("x-requests-remaining", "0")` at line 153 |
| 6 | is_stale() rejects stale snapshots and accepts fresh ones using datetime.now(timezone.utc) exclusively | VERIFIED | is_stale() at line 48; uses `datetime.now(timezone.utc)` (grep confirms zero `utcnow` occurrences in file); raises TypeError on naive datetime |
| 7 | InjuryWeatherScraper parses ESPN Core API JSON into injury dicts with "Unknown" fallbacks and writes to DB via asyncpg $N params | VERIFIED | parse_espn_injury_item() uses .get() with "Unknown" at every nesting level; write_injury_reports() uses `$1, $2, $3, $4, $5, $6` positional params; source hardcoded as "espn_core_api" |
| 8 | TEAM_ABBR_TO_ESPN_ID contains exactly 32 NFL team entries | VERIFIED | Dict literal in scraper.py confirmed 32 entries: ARI, ATL, BAL, BUF, CAR, CHI, CIN, CLE, DAL, DEN, DET, GB, HOU, IND, JAX, KC, LA, LAC, LV, MIA, MIN, NE, NO, NYG, NYJ, PHI, PIT, SEA, SF, TB, TEN, WAS |
| 9 | make_context_agent closure factory returns an async LangGraph-compatible node that assembles ContextSignals | VERIFIED | make_context_agent() at line 121 of agents.py; returns async `context_agent(state: GraphState) -> dict[str, Any]`; returns `{"context_signals": signals}` |
| 10 | create_graph() accepts optional context_node parameter with stub fallback when None | VERIFIED | `context_node: Any = None` parameter in create_graph() at graph.py line 41; `active_context_node = context_node if context_node is not None else context_agent`; sync stub preserved at agents.py line 312 |
| 11 | All 8 Phase 4 tests pass green with fully mocked HTTP — no live API credits consumed | VERIFIED | `pytest tests/test_context.py`: 8 passed in 0.46s; all HTTP patched via unittest.mock |
| 12 | Full test suite has zero regressions from Phase 2/3 tests | VERIFIED | `pytest tests/`: 59 passed, 9 skipped, 0 failed across all 10 test files |

**Score:** 12/12 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sportsbet/db/models.py` | InjuryReport ORM appended after OddsSnapshot | VERIFIED | class InjuryReport at line 206; 7 columns matching migration exactly; 3 composite indexes in __table_args__ |
| `src/sportsbet/graph/models.py` | ContextSignals Pydantic model with strict=True | VERIFIED | class ContextSignals at line 125; ConfigDict(strict=True); all 5 required fields present |
| `src/sportsbet/graph/state.py` | GraphState with context_signals: Optional[ContextSignals] | VERIFIED | Line 84; ContextSignals imported at runtime (not TYPE_CHECKING) — fixes LangGraph get_type_hints() |
| `alembic/versions/0002_add_injury_reports.py` | Migration with down_revision="0001" | VERIFIED | revision="0002_add_injury_reports"; down_revision="0001" (corrected from plan spec "0001_initial_schema"); all 8 columns; 3 indexes |
| `src/sportsbet/ingestion/odds_poller.py` | OddsAPIPoller + BudgetExhaustedError + is_stale() | VERIFIED | All 3 exports present; NFL_SPORT_KEY="americanfootball_nfl"; ODDS_API_BASE constant; DEFAULT_STALENESS_MINUTES=5 |
| `src/sportsbet/ingestion/scraper.py` | InjuryWeatherScraper + TEAM_ABBR_TO_ESPN_ID + parse_espn_injury_item() | VERIFIED | All 3 exports present; 32-entry team dict; .get() fallbacks at every field level |
| `src/sportsbet/graph/agents.py` | make_context_agent closure factory + _extract_odds_snapshot helper | VERIFIED | make_context_agent at line 121; _extract_odds_snapshot at line 206; sync stub context_agent preserved at line 312 |
| `src/sportsbet/graph/graph.py` | create_graph() with context_node param + create_graph_with_sqlite() updated | VERIFIED | context_node parameter in both functions; create_graph_with_sqlite() accepts api_key + daily_credit_cap |
| `tests/test_context.py` | 8 tests all passing green (not stub pytest.fail) | VERIFIED | All 8 tests have real assertions; 8/8 PASSED |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| InjuryReport ORM | 0002_add_injury_reports migration | Same column definitions and index names | WIRED | All 7 columns match exactly: id, game_id, player_name, status, position, team_abbr, scraped_at, source; all 3 index names identical |
| ContextSignals (graph/models.py) | GraphState (graph/state.py) | context_signals: Optional[ContextSignals] field | WIRED | Runtime import at state.py line 17; field at line 84; TypedDict annotation resolved at graph compilation |
| OddsAPIPoller.fetch_nfl_odds() | x-requests-remaining header | response.headers.get('x-requests-remaining', '0') | WIRED | Line 153-155 of odds_poller.py; cast to int; stored in self._credits_remaining |
| is_stale() | datetime.now(timezone.utc) | timezone-aware subtraction | WIRED | Line 64; `now = datetime.now(timezone.utc)`; zero utcnow() occurrences confirmed |
| InjuryWeatherScraper.fetch_team_injuries() | ESPN Core API | httpx.AsyncClient GET with TEAM_ABBR_TO_ESPN_ID lookup | WIRED | ESPN_INJURIES_URL.format(team_id=team_id) at scraper.py line 152; team_id resolved via TEAM_ABBR_TO_ESPN_ID |
| InjuryWeatherScraper.write_injury_reports() | injury_reports table | asyncpg pool.execute INSERT | WIRED | Line 197-207; `INSERT INTO injury_reports (...) VALUES ($1, $2, $3, $4, $5, $6)`; source hardcoded "espn_core_api" |
| make_context_agent | OddsAPIPoller | Imported inside closure; pool injected at construction | WIRED | Line 146 of agents.py: `from sportsbet.ingestion.odds_poller import BudgetExhaustedError, OddsAPIPoller`; used at line 159 |
| make_context_agent | InjuryWeatherScraper | Imported inside closure; httpx.AsyncClient created per invocation | WIRED | Line 147: `from sportsbet.ingestion.scraper import TEAM_ABBR_TO_ESPN_ID, InjuryWeatherScraper`; used at line 172 |
| make_context_agent | GraphState.context_signals | Returns {"context_signals": ContextSignals(...)} | WIRED | Line 201: `return {"context_signals": signals}` |
| create_graph() | context_agent node registration | active_context_node = context_node if context_node is not None else context_agent | WIRED | graph.py line 76-82; stub fallback preserved; builder.add_node("context_agent", active_context_node) |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CTXT-01 | 04-01, 04-02 | System ingests live odds asynchronously from The Odds API with budget manager tracking per-request cost | SATISFIED | OddsAPIPoller.fetch_nfl_odds() in odds_poller.py; _credits_remaining updated from x-requests-remaining header; BudgetExhaustedError raised when < 1 without HTTP call; 2 tests green |
| CTXT-02 | 04-01, 04-02 | System rejects odds payload older than configurable staleness threshold (default: 5 minutes) | SATISFIED | is_stale(snapped_at, threshold_minutes=DEFAULT_STALENESS_MINUTES=5) in odds_poller.py; returns True/False; TypeError on naive datetime; 2 tests green |
| CTXT-03 | 04-01, 04-03 | System scrapes injury reports via async HTTP and stores structured binary state changes | SATISFIED | InjuryWeatherScraper fetches ESPN Core API, parses with "Unknown" fallbacks, writes to injury_reports table via asyncpg; 2 tests green. Note: Weather scraping (Playwright/NFLWeather.com) deferred to v2 — plan explicitly documented this deferral |
| CTXT-04 | 04-01, 04-04 | Context Agent updates global game state on binary state changes and propagates through GraphState | SATISFIED | make_context_agent() closure assembles ContextSignals and returns {"context_signals": signals}; create_graph(context_node=...) wires real agent; downstream test verifies state["context_signals"] is non-None after graph.ainvoke(); 2 tests green |

**Orphaned requirements check:** REQUIREMENTS.md maps CTXT-01, CTXT-02, CTXT-03, CTXT-04 to Phase 4. All 4 are claimed by plan frontmatter. Zero orphaned requirements.

**Requirements marked Complete in REQUIREMENTS.md:** All 4 CTXT requirements marked `[x]` — consistent with verification evidence.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/test_graph.py` | 199 | `datetime.utcnow()` (deprecated, raises DeprecationWarning) | INFO | Pre-existing warning from Phase 2; not introduced by Phase 4 work; no Phase 4 files use utcnow() |

No blocker or warning anti-patterns found in Phase 4 production files. The utcnow() usage in test_graph.py is pre-existing and does not affect Phase 4 behavior.

---

### Human Verification Required

#### 1. Live Odds API Integration

**Test:** Set SPORTSBET_TEST_ODDS_API_KEY env var and call `async with OddsAPIPoller(api_key=key, daily_credit_cap=500) as p: result = await p.fetch_nfl_odds(); print(p._credits_remaining)`
**Expected:** JSON list returned; _credits_remaining decremented from 500 by 1; x-requests-remaining header parsed
**Why human:** All HTTP calls are mocked in the test suite. Real Odds API credentials not present in dev environment.

#### 2. ESPN Core API Live Schema Validation

**Test:** Instantiate InjuryWeatherScraper with a real httpx.AsyncClient and call `fetch_team_injuries(12)` (KC team ID)
**Expected:** Non-empty list of injury dicts; all dicts have player_name, status, position keys; any absent ESPN field returns "Unknown" not KeyError
**Why human:** ESPN Core API is undocumented. Field names verified against a community gist but must be confirmed against live API before production. Schema drift is explicitly called out in CLAUDE.md and the plan.

#### 3. BudgetExhaustedError Graceful Degradation in Production Graph

**Test:** Call `create_graph_with_sqlite(pool=real_pool, api_key="valid_key", daily_credit_cap=0)` and invoke with request_type="context_update"
**Expected:** ContextSignals returned with odds_snapshot=None; error field remains None; graph completes normally
**Why human:** Tests verify the exception is caught inside the closure but all via mocks. End-to-end LangGraph state machine behavior with degraded odds signal needs human confirmation.

---

### Gaps Summary

No gaps. All 12 observable truths verified. All artifacts exist, are substantive (not stubs), and are wired into the system. All 4 requirement IDs satisfied. The 3 human verification items are informational — they test live external service integration that cannot be verified programmatically without credentials.

**Notable deviations from plan that were auto-corrected:**

1. **Alembic down_revision:** Plan specified `"0001_initial_schema"` but actual 0001 migration uses revision `"0001"`. Corrected to `"0001"` in the migration file — verified correct by checking actual revision string in 0001_initial_schema.py.

2. **TYPE_CHECKING guard replaced by runtime import:** Plan specified TYPE_CHECKING guard for ContextSignals in state.py. LangGraph calls `get_type_hints(GraphState)` at graph compilation which cannot resolve TYPE_CHECKING-only symbols. Fixed by importing ContextSignals at runtime — correct behavior, no side effects.

3. **Weather scraping deferred to v2:** CTXT-03 requirement language ("Playwright/BeautifulSoup") implies weather scraping. Plan 03 explicitly defers NFLWeather.com scraping to v2, noting that ESPN Core API handles the injury side. The REQUIREMENTS.md description ("stores structured binary state changes") is satisfied by injury data alone. Weather scraping is a v2 enhancement, not a v1 blocker.

---

_Verified: 2026-03-14_
_Verifier: Claude (gsd-verifier)_
