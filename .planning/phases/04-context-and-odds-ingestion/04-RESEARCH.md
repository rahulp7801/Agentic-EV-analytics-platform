# Phase 4: Context and Odds Ingestion - Research

**Researched:** 2026-03-13
**Domain:** Async HTTP polling (The Odds API), web scraping (Playwright/BeautifulSoup), LangGraph state propagation
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CTXT-01 | System ingests live odds asynchronously from The Odds API with a budget manager that tracks per-request cost and enforces a configurable daily API spend cap | Odds API credit-per-request model documented; httpx AsyncClient lifecycle + response header `x-requests-remaining` pattern verified |
| CTXT-02 | System rejects any odds payload older than a configurable staleness threshold (default: 5 minutes) before passing to the Arbitrage Agent | datetime.now(timezone.utc) staleness comparison pattern verified; Pydantic validator guard documented |
| CTXT-03 | System scrapes qualitative signals (injury reports, weather forecasts) via async Playwright/BeautifulSoup and stores structured binary state changes | ESPN Core API JSON endpoints verified; NFLWeather URL pattern verified; Playwright async context manager verified |
| CTXT-04 | Context Agent updates a global game state JSON on binary state changes and propagates the updated state through GraphState | LangGraph partial state dict update pattern verified in existing codebase; ContextSignals Pydantic model needed |
</phase_requirements>

---

## Summary

Phase 4 builds the two live-data pipelines that feed all downstream agents: the Odds API poller and the qualitative signal scraper. Both pipelines are async, Pydantic-validated, and write to PostgreSQL. The Odds API pipeline must budget-gate every request using response-header credits (`x-requests-remaining`) and enforce a configurable daily spend cap persisted across calls. The scraper pipeline must handle dynamic HTML (Playwright) and produce structured binary state changes written to a new `injury_reports` table (a Wave 0 migration gap). The Context Agent node replaces the Phase 2 stub and propagates a `ContextSignals` Pydantic object through GraphState so all downstream agents read from state rather than re-fetching.

The project already has: the `odds_snapshots` table schema, the `OddsSnapshotCreate` writer, and the stub `context_agent` node. Phase 4 wires real logic into the stub using the same closure-factory pattern established in Phase 3 (`make_quant_agent`).

**Primary recommendation:** Use `httpx.AsyncClient` (already implicitly available, pairs well with asyncpg event loop) for The Odds API calls. Use `playwright.async_api` for JavaScript-heavy pages; fall back to `httpx` + BeautifulSoup for static HTML like NFLWeather. Never use `datetime.utcnow()` — use `datetime.now(timezone.utc)` throughout for staleness guards.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | >=0.27 | Async HTTP client for The Odds API polling | Native asyncio, connection pooling, response header access, h2 support |
| playwright (async_api) | >=1.44 | Dynamic page rendering for JS-heavy injury pages | First-class async API; auto-waits; BeautifulSoup cannot execute JS |
| beautifulsoup4 | >=4.12 | HTML parsing after Playwright or httpx fetch | Lightweight, no JS required; pairs with lxml parser for speed |
| lxml | >=5.2 | HTML/XML parser backend for BeautifulSoup | 10-50x faster than html.parser on large pages |
| pydantic v2 | >=2.7 (already installed) | ContextSignals, OddsIngestResult models | Non-negotiable per CLAUDE.md |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | >=8.3 | Retry with exponential backoff | Wrapping Odds API calls and scraper fetches for transient failures |
| asyncpg | >=0.29 (already installed) | Async PostgreSQL writes for odds + injury rows | Hot-path agent writes; pool already created in Phase 3 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx | aiohttp | httpx has cleaner API, response.headers dict access identical; aiohttp requires more boilerplate |
| Playwright | Selenium | Playwright async API is native; Selenium requires separate thread pool for async compatibility |
| tenacity | manual retry loop | tenacity provides decorator-based backoff with jitter; eliminates retry boilerplate |

**Installation:**
```bash
pip install httpx tenacity playwright beautifulsoup4 lxml
playwright install chromium
```

Note: `httpx` may already be present as a transitive dependency of `langgraph`. Verify with `pip show httpx`.

---

## Architecture Patterns

### Recommended Project Structure

```
src/sportsbet/
├── ingestion/
│   ├── odds.py           # EXISTING: OddsSnapshotCreate + write_odds_snapshot
│   ├── odds_poller.py    # NEW: OddsAPIPoller (async httpx, budget manager)
│   └── scraper.py        # NEW: InjuryWeatherScraper (async Playwright + BS4)
├── graph/
│   ├── agents.py         # EXTEND: make_context_agent(pool) closure, replace stub
│   ├── models.py         # EXTEND: add ContextSignals Pydantic model
│   └── state.py          # EXTEND: add context_signals field to GraphState
└── db/
    └── models.py         # EXTEND: add InjuryReport ORM model
alembic/versions/
    └── 0002_add_injury_reports.py  # NEW: Wave 0 migration for injury_reports table
```

### Pattern 1: Async Odds Poller with Budget Manager

**What:** A class that wraps httpx.AsyncClient, tracks credit spend from response headers, and raises a hard stop when the daily budget cap is reached.

**When to use:** Every call to The Odds API goes through this class.

**Key design:** The Odds API returns three headers after each request:
- `x-requests-remaining` — credits left today
- `x-requests-used` — credits consumed today
- `x-requests-last` — credits consumed by the last request

The budget manager reads `x-requests-remaining` after each response. If remaining credits fall below the configured floor, subsequent calls raise `BudgetExhaustedError` without hitting the API.

**Cost model (verified from official docs):**
- `GET /v4/sports/{sport}/odds` = 1 credit × number of regions × number of markets
- `GET /v4/historical/sports/{sport}/odds` = 10 credits × regions × markets
- Use `GET /v4/sports` (free, no quota cost) to enumerate available sports/events

**Example:**
```python
# Source: The Odds API v4 official docs (https://the-odds-api.com/liveapi/guides/v4/)
import httpx
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict

ODDS_API_BASE = "https://api.the-odds-api.com"
NFL_SPORT_KEY = "americanfootball_nfl"  # verified sport key

class OddsAPIPoller:
    """Wraps httpx.AsyncClient with credit-tracking budget manager."""

    def __init__(self, api_key: str, daily_credit_cap: int) -> None:
        self._api_key = api_key
        self._daily_credit_cap = daily_credit_cap
        self._credits_remaining: int | None = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OddsAPIPoller":
        self._client = httpx.AsyncClient(base_url=ODDS_API_BASE, timeout=10.0)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    async def fetch_nfl_odds(
        self, regions: str = "us", markets: str = "h2h,spreads,totals"
    ) -> dict:
        if self._credits_remaining is not None and self._credits_remaining < 1:
            raise BudgetExhaustedError(f"Daily cap reached: {self._daily_credit_cap}")
        response = await self._client.get(
            f"/v4/sports/{NFL_SPORT_KEY}/odds",
            params={"apiKey": self._api_key, "regions": regions, "markets": markets},
        )
        response.raise_for_status()
        self._credits_remaining = int(response.headers.get("x-requests-remaining", 0))
        return response.json()
```

### Pattern 2: Staleness Guard (CTXT-02)

**What:** A Pydantic validator or standalone function that rejects any `AgentOddsSnapshot` whose `snapped_at` is older than the configured threshold.

**When to use:** Called after fetching the latest odds snapshot from PostgreSQL, before passing to the Arbitrage Agent.

**Critical rule:** Always use `datetime.now(timezone.utc)` — never `datetime.utcnow()` (deprecated in Python 3.12, removed in 3.13). The `snapped_at` column in PostgreSQL is `TIMESTAMP WITH TIME ZONE`, so asyncpg returns it as timezone-aware; the comparison will not raise a TypeError.

**Example:**
```python
# Source: Python docs (https://docs.python.org/3/library/datetime.html)
from datetime import datetime, timedelta, timezone

DEFAULT_STALENESS_THRESHOLD = timedelta(minutes=5)

def is_stale(snapped_at: datetime, threshold: timedelta = DEFAULT_STALENESS_THRESHOLD) -> bool:
    """Return True if the snapshot is older than threshold.

    snapped_at MUST be timezone-aware (asyncpg returns TIMESTAMPTZ as aware).
    Raises TypeError if naive datetime is passed — caught at test time.
    """
    return (datetime.now(timezone.utc) - snapped_at) > threshold
```

### Pattern 3: Async Scraper with Playwright + BeautifulSoup

**What:** An async function that launches a Playwright browser context, navigates to the target page, waits for content to load, extracts HTML, and parses it with BeautifulSoup.

**When to use:** Any page that requires JavaScript execution (e.g., dynamic injury status grids). For static HTML pages (NFLWeather), httpx alone is sufficient.

**ESPN Core API alternative (preferred over HTML scraping):**
The ESPN Core API provides structured JSON injury data without requiring Playwright:
```
GET https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams/{team_id}/injuries?limit=100
```
Returns JSON with player name, injury type, status (Out/Questionable/Probable/Doubtful), and return date. No API key required. This is **lower fragility** than HTML scraping and should be preferred for injury signals.

**Playwright pattern (for pages without a JSON API):**
```python
# Source: Playwright Python docs (https://playwright.dev/python/docs/api/class-page)
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def scrape_page(url: str) -> BeautifulSoup:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        html = await page.content()
        await browser.close()
    return BeautifulSoup(html, "lxml")
```

**NFLWeather URL pattern (static HTML, use httpx):**
```
http://nflweather.com/en/week/{year}/week-{week}/
```
Returns an HTML table with Away team, Game, Home team, Time (ET), TV, and Forecast columns. Parse with BeautifulSoup + lxml; no Playwright needed.

### Pattern 4: Context Agent Closure Factory (CTXT-04)

**What:** Same closure-factory pattern as `make_quant_agent(pool)` from Phase 3. The Context Agent reads injected context (pool, http client) at construction time and returns an async LangGraph-compatible node.

**When to use:** Replaces the stub `context_agent` in `agents.py`. The `create_graph()` factory in `graph.py` gains a `context_node` parameter parallel to `quant_node`.

```python
# Pattern established in Phase 3 (src/sportsbet/graph/agents.py)
def make_context_agent(pool: asyncpg.Pool, api_key: str, daily_credit_cap: int):
    async def context_agent(state: GraphState) -> dict[str, Any]:
        # 1. Fetch latest odds via OddsAPIPoller
        # 2. Validate staleness via is_stale()
        # 3. Scrape injury/weather signals
        # 4. Build ContextSignals Pydantic object
        # 5. Return partial state dict: {"context_signals": signals}
    return context_agent
```

### Pattern 5: ContextSignals Pydantic Model

**What:** New model in `src/sportsbet/graph/models.py` following existing model conventions (ConfigDict strict=True, Decimal for probabilities, Optional for nullable fields).

```python
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class ContextSignals(BaseModel):
    """Structured game context produced by the Context Agent.

    Propagated through GraphState.context_signals so all downstream
    agents (Quant, Arbitrage) read from state rather than re-fetching.
    """
    model_config = ConfigDict(strict=True)

    game_id: str
    injury_flags: dict[str, str]          # {"P. Mahomes": "Out"}
    weather_json: Optional[dict] = None   # None for indoor stadiums
    odds_snapshot: Optional[AgentOddsSnapshot] = None
    signals_captured_at: datetime         # UTC timestamp of scrape/fetch
```

**GraphState extension:** Add `context_signals: ContextSignals | None` to `GraphState` TypedDict in `state.py`. Use `None` default (set via `total=False` or explicit `None`).

### Anti-Patterns to Avoid

- **Calling `datetime.utcnow()`:** Deprecated in 3.12 — always use `datetime.now(timezone.utc)`.
- **Launching a new Playwright browser per call:** Expensive (500ms+ startup). Reuse browser context within a scraper session; close only at session end.
- **Re-fetching odds inside the Arbitrage Agent:** CTXT-04 explicitly requires downstream agents read from `GraphState.context_signals`, not from the API.
- **Storing raw American odds integers in `AgentOddsSnapshot.implied_probability`:** Existing Phase 2 decision — conversion happens at ingestion time (see `AgentOddsSnapshot` docstring in `models.py`).
- **Using `x-requests-remaining` as the sole budget gate:** The header reflects server-side credit state. Persist the last known value to a file or DB row to survive process restarts within the same UTC day.
- **Multiple httpx.AsyncClient instances per polling loop:** Creates redundant connection pools. Use a single scoped client (context manager or injected via closure).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry with backoff | Custom sleep loop | `tenacity.retry` with `wait_exponential` | Handles jitter, max attempts, exception filtering correctly |
| HTML parsing after Playwright | Manual regex on HTML | BeautifulSoup + lxml | Regex on HTML is brittle; BS4 handles malformed HTML gracefully |
| Injury data JSON parsing | Custom ESPN HTML scraper | ESPN Core API direct JSON request | ESPN Core API returns structured JSON; HTML scraping breaks on layout changes |
| Async HTTP client | `urllib` / `requests` in thread | `httpx.AsyncClient` | requests is sync-only; threading defeats asyncio event loop efficiency |

**Key insight:** The ESPN Core API (`sports.core.api.espn.com`) returns structured JSON injury data without authentication, making it far more robust than HTML scraping. Use it as the primary injury signal source; reserve Playwright for sites with no JSON API.

---

## Common Pitfalls

### Pitfall 1: Naive vs Aware Datetime in Staleness Check

**What goes wrong:** `datetime.now() - snapped_at` raises `TypeError: can't subtract offset-naive and offset-aware datetimes` because PostgreSQL `TIMESTAMP WITH TIME ZONE` columns return timezone-aware datetimes via asyncpg, but `datetime.now()` returns naive.

**Why it happens:** Forgetting that asyncpg preserves timezone info from `TIMESTAMPTZ` columns.

**How to avoid:** Always compare `datetime.now(timezone.utc)` with `snapped_at`. Add a unit test that passes a timezone-aware fixture through `is_stale()`.

**Warning signs:** `TypeError` on subtraction; test passing with naive fixture but failing in production.

### Pitfall 2: Odds API Credit Depletion During Testing

**What goes wrong:** Integration tests hit the live Odds API and exhaust the daily credit cap during development.

**Why it happens:** Tests don't mock the HTTP layer.

**How to avoid:** All tests must mock `httpx.AsyncClient.get` responses using `unittest.mock.AsyncMock` or `respx` (httpx-native mock library). Gate live API tests behind an env var (`SPORTSBET_TEST_ODDS_API_KEY`) with `pytest.mark.skipif`.

**Warning signs:** Credits depleted before market hours; 429 status codes from real API calls in CI.

### Pitfall 3: Playwright Browser Not Closed on Exception

**What goes wrong:** If an exception occurs mid-scrape, the Chromium process is never killed, leaking memory and file handles.

**Why it happens:** Not using `async with async_playwright()` context manager.

**How to avoid:** Always use `async with async_playwright() as p:` and `async with await p.chromium.launch() as browser:`. The context managers guarantee cleanup even on exception.

### Pitfall 4: injury_reports Table Missing from Schema

**What goes wrong:** CTXT-03 writes structured injury state changes to `injury_reports`, but this table does not exist in the current ORM models or Alembic migration (confirmed: `0001_initial_schema.py` has no `injury_reports` table).

**Why it happens:** The table was not included in the Phase 1 data foundation.

**How to avoid:** Wave 0 of Phase 4 must create `InjuryReport` ORM model in `db/models.py` and a new Alembic migration `0002_add_injury_reports.py`. The migration must be hand-written (not autogenerate) per the Phase 1 decision about composite indexes.

**Warning signs:** `ProgrammingError: relation "injury_reports" does not exist` on first scraper write.

### Pitfall 5: Budget Manager State Not Persisted Across Process Restarts

**What goes wrong:** The `_credits_remaining` counter in `OddsAPIPoller` resets to `None` when the process restarts. Multiple restarts within the same UTC day can exceed the configured cap.

**Why it happens:** In-memory-only credit tracking.

**How to avoid:** Persist the last known `x-requests-remaining` value to a small table or to the PostgreSQL `odds_snapshots` table as a metadata row. On startup, load the persisted value if the last write was within the current UTC day.

### Pitfall 6: ESPN Core API Team IDs Are Not Abbreviations

**What goes wrong:** The ESPN Core API uses numeric team IDs (e.g., `8` for the Cardinals, not `ARI`), not the 2-3 letter abbreviations used in `GraphState`.

**Why it happens:** ESPN's internal data model uses different identifiers from the nflreadpy/NFL-standard team abbreviations.

**How to avoid:** Maintain a static mapping dict `TEAM_ABBR_TO_ESPN_ID: dict[str, int]` in the scraper module. This is a small, stable lookup (32 teams) and does not need a DB table.

---

## Code Examples

Verified patterns from official sources:

### Odds API Response Structure

```python
# Source: The Odds API v4 docs (https://the-odds-api.com/liveapi/guides/v4/)
# GET /v4/sports/americanfootball_nfl/odds?regions=us&markets=h2h
# Response structure:
[
    {
        "id": "event_id_string",
        "sport_key": "americanfootball_nfl",
        "sport_title": "NFL",
        "commence_time": "2025-10-05T17:00:00Z",  # ISO-8601 UTC
        "home_team": "Kansas City Chiefs",
        "away_team": "Los Angeles Chargers",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2025-10-05T16:55:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Kansas City Chiefs", "price": -180},
                            {"name": "Los Angeles Chargers", "price": +155},
                        ]
                    }
                ]
            }
        ]
    }
]
# Response headers: x-requests-remaining, x-requests-used, x-requests-last
```

### Budget Manager Credit Check

```python
# Source: httpx docs (https://www.python-httpx.org/async/)
response = await client.get("/v4/sports/americanfootball_nfl/odds", params=params)
response.raise_for_status()
remaining = int(response.headers.get("x-requests-remaining", "0"))
used_last = int(response.headers.get("x-requests-last", "1"))
# Update persistent budget state here
```

### Staleness Guard

```python
# Source: Python stdlib docs (https://docs.python.org/3/library/datetime.html)
from datetime import datetime, timedelta, timezone

def is_stale(snapped_at: datetime, threshold_minutes: int = 5) -> bool:
    """True if snapped_at is older than threshold_minutes ago (UTC-aware)."""
    threshold = timedelta(minutes=threshold_minutes)
    return (datetime.now(timezone.utc) - snapped_at) > threshold
```

### ESPN Core API Injury Fetch

```python
# Source: ESPN Core API (https://sports.core.api.espn.com/) verified via community docs
import httpx

ESPN_INJURIES_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    "/teams/{team_id}/injuries?limit=100"
)

async def fetch_team_injuries(client: httpx.AsyncClient, team_id: int) -> list[dict]:
    response = await client.get(ESPN_INJURIES_URL.format(team_id=team_id))
    response.raise_for_status()
    data = response.json()
    return data.get("items", [])
```

### InjuryReport ORM Model (Wave 0 Gap)

```python
# Pattern follows existing ORM conventions in src/sportsbet/db/models.py
class InjuryReport(Base):
    __tablename__ = "injury_reports"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    game_id: Mapped[Optional[str]] = mapped_column(String(20), ForeignKey("games.game_id"))
    player_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "Out"|"Questionable"|etc
    position: Mapped[Optional[str]] = mapped_column(String(5))
    scraped_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # "espn_core_api"

    __table_args__ = (
        Index("idx_injury_game_id", "game_id"),
        Index("idx_injury_scraped_at", "scraped_at"),
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `datetime.utcnow()` | `datetime.now(timezone.utc)` | Python 3.12 (deprecated), 3.13 (removed) | Staleness guard will raise `DeprecationWarning` on 3.12; TypeError on naive-aware subtraction |
| Selenium for dynamic scraping | Playwright async API | 2021+ | Native asyncio; no threading hack required; auto-wait eliminates flaky sleeps |
| `requests` in thread pool | `httpx.AsyncClient` | 2023+ standard | Single event loop; no thread overhead; identical API surface to requests |
| ESPN HTML scraping | ESPN Core API JSON | Always available; widely documented 2022+ | No Playwright needed for injury data; structured response survives UI redesigns |

**Deprecated/outdated:**
- `playwright.sync_api`: Do not use in async LangGraph nodes — blocks the event loop.
- `nfl_data_py` for any new ingestion: Archived September 2025 per project decision; all imports use `nflreadpy`.

---

## Open Questions

1. **ESPN Core API stability for injury data**
   - What we know: The API is undocumented but widely used by the sports data community; endpoints observed working as of 2025 season.
   - What's unclear: No SLA; ESPN can change schema without notice.
   - Recommendation: Add a schema version check in the scraper and log a warning if expected fields are absent, rather than raising. Fall back to `status="Unknown"` for any malformed record.

2. **Odds API sport key for preseason / postseason NFL**
   - What we know: `americanfootball_nfl` covers regular season. Preseason may be `americanfootball_nfl_preseason`.
   - What's unclear: Whether postseason uses the same key or a separate one.
   - Recommendation: On the first Odds API call, fetch `/v4/sports` (free, no quota) and log all available NFL sport keys to confirm.

3. **Persisting budget state across process restarts**
   - What we know: `x-requests-remaining` is the authoritative server-side count; the in-memory counter resets on restart.
   - What's unclear: Whether a lightweight file-based solution or a DB row is better for the v1 single-user setup.
   - Recommendation: Write the `x-requests-remaining` value and a UTC date stamp to a `api_budget` key in a small `settings_cache` table or a JSON sidecar file. On startup, load it only if the date matches today.

4. **NFLWeather.com scraping reliability**
   - What we know: URL pattern `http://nflweather.com/en/week/{year}/week-{week}/` is documented in community resources; data is updated twice per hour.
   - What's unclear: Whether the site has anti-scraping measures (Cloudflare, rate limiting).
   - Recommendation: Use `httpx` with a realistic User-Agent header as the first attempt; fall back to Playwright only if a Cloudflare challenge page is detected in the response.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2 + pytest-asyncio 0.23 |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `pytest tests/test_context.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CTXT-01 | Odds API call returns odds, writes to DB, budget manager tracks credits | integration | `pytest tests/test_context.py::test_odds_poller_writes_snapshot -x` | Wave 0 |
| CTXT-01 | BudgetExhaustedError raised when credits_remaining < 1 | unit | `pytest tests/test_context.py::test_budget_exhausted_raises -x` | Wave 0 |
| CTXT-02 | Odds payload older than 5 min rejected before Arbitrage Agent | unit | `pytest tests/test_context.py::test_staleness_guard_rejects_stale -x` | Wave 0 |
| CTXT-02 | Fresh payload (within threshold) passes staleness check | unit | `pytest tests/test_context.py::test_staleness_guard_passes_fresh -x` | Wave 0 |
| CTXT-03 | Scraper writes structured binary state change to injury_reports | integration | `pytest tests/test_context.py::test_scraper_writes_injury_report -x` | Wave 0 |
| CTXT-03 | Injury status "Out" extracted from ESPN Core API JSON fixture | unit | `pytest tests/test_context.py::test_espn_injury_parsing -x` | Wave 0 |
| CTXT-04 | Context Agent returns ContextSignals in GraphState partial dict | unit | `pytest tests/test_context.py::test_context_agent_updates_graphstate -x` | Wave 0 |
| CTXT-04 | Downstream agents read context_signals from GraphState, not re-fetch | integration | `pytest tests/test_context.py::test_downstream_reads_state -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_context.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_context.py` — all CTXT-01 through CTXT-04 test stubs
- [ ] `alembic/versions/0002_add_injury_reports.py` — hand-written migration for `injury_reports` table
- [ ] `src/sportsbet/db/models.py` — `InjuryReport` ORM model
- [ ] `src/sportsbet/graph/models.py` — `ContextSignals` Pydantic model
- [ ] `src/sportsbet/graph/state.py` — `context_signals` field added to `GraphState`
- [ ] Framework additions: `pip install httpx tenacity playwright beautifulsoup4 lxml && playwright install chromium`

---

## Sources

### Primary (HIGH confidence)

- The Odds API v4 official docs (https://the-odds-api.com/liveapi/guides/v4/) — sport keys, endpoint URLs, credit cost table, response header names
- Python stdlib datetime docs (https://docs.python.org/3/library/datetime.html) — `datetime.now(timezone.utc)` pattern, deprecation of `utcnow()`
- httpx official docs (https://www.python-httpx.org/async/) — AsyncClient context manager, connection pooling, response headers
- Playwright Python docs (https://playwright.dev/python/) — `async_playwright()` context manager, `wait_until="networkidle"`

### Secondary (MEDIUM confidence)

- ESPN Core API gist (https://gist.github.com/nntrn/ee26cb2a0716de0947a0a4e9a157bc1c) — team injuries endpoint URL, pagination pattern; undocumented API but widely verified by community
- NFLWeather.com URL pattern (`http://nflweather.com/en/week/{year}/week-{week}/`) — documented in community repos; HTML table structure verified in multiple blog posts

### Tertiary (LOW confidence)

- ESPN Core API injury response field names (`status`, `athlete`, `type`) — verified via community docs but no official ESPN schema; flag for validation against live response
- NFLWeather.com anti-scraping posture — no official statement; inferred from absence of documented protections in community scraping posts

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — httpx, Playwright, BeautifulSoup all verified in official docs; tenacity is standard retry library
- Architecture: HIGH — closure-factory pattern directly matches Phase 3 pattern in existing codebase; LangGraph partial dict update verified in existing agents.py
- Pitfalls: HIGH — timezone pitfall verified by Python docs; ESPN numeric team IDs verified via community gist; Playwright cleanup verified in official docs
- ESPN injury endpoint: MEDIUM — undocumented API but broadly used by data community; field names need live validation in Wave 0

**Research date:** 2026-03-13
**Valid until:** 2026-04-13 (30 days; all libs stable; ESPN Core API may change without notice)
