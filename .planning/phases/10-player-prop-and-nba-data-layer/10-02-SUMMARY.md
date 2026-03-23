---
phase: 10-player-prop-and-nba-data-layer
plan: "02"
subsystem: database
tags: [nba_api, pandas, sqlalchemy, ingestion, nba, player-stats]

# Dependency graph
requires:
  - phase: 10-01
    provides: nba_player_stats table migration + NBAPlayerStats ORM model
provides:
  - ingest_nba_seasons() function loading season-aggregate NBA player stats via nba_api
  - NBA_COLUMNS whitelist and RENAME_MAP constants
  - CLI entry point: python -m sportsbet.ingestion.nba --seasons
  - 5 unit tests covering season format, column whitelist, gc, sleep, timeout handling
affects:
  - phase-12-nba-quant-engine (consumes nba_player_stats table data)

# Tech tracking
tech-stack:
  added: [nba_api]
  patterns:
    - "year-by-year ingestion loop with gc.collect() after each season (mirrors pbp.py pattern)"
    - "time.sleep(1) mandatory between nba_api calls for NBA.com rate limit compliance"
    - "NBA_COLUMNS whitelist + RENAME_MAP — same two-step filter+rename as pbp.py"
    - "nba_api returns pandas DataFrames directly — no .to_pandas() call needed (unlike nflreadpy/Polars)"

key-files:
  created:
    - src/sportsbet/ingestion/nba.py
    - tests/test_nba_ingestion.py
  modified: []

key-decisions:
  - "nba_api returns pandas DataFrames (not Polars) — no .to_pandas() call required; documented in module docstring"
  - "time.sleep(1) placed after LeagueDashPlayerStats instantiation (before get_data_frames()) — matches NBA.com rate limit policy per research"
  - "broad Exception catch covers ReadTimeout, httpx.ReadTimeout, and connection errors — avoids import dependency on requests/httpx in src"
  - "nba_api installed to site-packages/ (Windows pip --target workaround) — consistent with existing site-packages pattern"

patterns-established:
  - "NBA ingestion pattern: LeagueDashPlayerStats -> get_data_frames()[0] -> column whitelist -> rename -> add season col -> to_sql(append)"

requirements-completed: [NBA-01]

# Metrics
duration: 3min
completed: 2026-03-23
---

# Phase 10 Plan 02: NBA Player Stats Ingestion Summary

**NBA player season-aggregate stats ingestion via nba_api.LeagueDashPlayerStats with rate limiting, column whitelisting, and per-season timeout handling — 5 TDD tests green**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-23T00:52:42Z
- **Completed:** 2026-03-23T00:55:58Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- Implemented `ingest_nba_seasons()` loading NBA player totals year-by-year into `nba_player_stats`
- TDD cycle: 5 RED tests confirmed ImportError, then all 5 GREEN after implementation
- Full test suite: 106 passed, 10 skipped, 0 failures — no regressions from Plan 01

## Task Commits

Each task was committed atomically:

1. **Task 1: TDD RED — test stubs for NBA ingestion** - `038cc8a` (test)
2. **Task 2: Implement ingest_nba_seasons() + CLI entry point** - `250b3fd` (feat)
3. **Task 3: Full suite green + migration integration test** - verified (no new files)

## Files Created/Modified

- `src/sportsbet/ingestion/nba.py` - ingest_nba_seasons() with NBA_COLUMNS whitelist, RENAME_MAP, gc/sleep/timeout handling, CLI __main__ block
- `tests/test_nba_ingestion.py` - 5 unit tests: season format, column whitelist, gc.collect, time.sleep, timeout skip

## Decisions Made

- `nba_api` returns pandas DataFrames directly (not Polars like nflreadpy) — no `.to_pandas()` call needed; documented clearly in module docstring to prevent future confusion
- `time.sleep(1)` placed after `LeagueDashPlayerStats()` instantiation (which triggers the HTTP call) and before `get_data_frames()` — correct placement per NBA.com rate limit policy
- Broad `except Exception` catch handles all timeout variants (requests.ReadTimeout, httpx.ReadTimeout, generic) without importing those libraries as hard dependencies in the module
- `nba_api` installed to `site-packages/` using `pip install --target` — consistent with existing Windows workaround established in Phase 01

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed nba_api package**
- **Found during:** Task 2 (implementation)
- **Issue:** `nba_api` not installed; module import failed with `ModuleNotFoundError: No module named 'nba_api'`
- **Fix:** `pip install nba_api --target site-packages` — consistent with existing site-packages pattern for Windows
- **Files modified:** site-packages/ (untracked, excluded from git)
- **Verification:** `pytest tests/test_nba_ingestion.py` passes 5/5 after install
- **Committed in:** 250b3fd (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking dependency)
**Impact on plan:** Required to execute any nba_api import. No scope creep.

## Issues Encountered

- `python -m sportsbet.ingestion.nba --help` requires explicit `PYTHONPATH=src;site-packages` without editable install — standard behavior in this project; pytest sets pythonpath via pyproject.toml config

## Next Phase Readiness

- `nba_player_stats` table is migrated (Plan 01) and ingestion is implemented (this plan)
- Phase 12 NBA quant engine can query player season totals for distribution analysis
- No blockers

---
*Phase: 10-player-prop-and-nba-data-layer*
*Completed: 2026-03-23*
