---
phase: 18-situational-game-log-prop-queries
plan: 01
subsystem: database
tags: [nba_api, sqlalchemy, alembic, pandas, postgresql, gamelog, ingestion]

requires:
  - phase: 10-player-prop-and-nba-data-layer
    provides: NBAPlayerStats ORM, nba_api ingestion pattern, migration 0004 base

provides:
  - NBAPlayerGameLog ORM model with per-game columns (is_home, opponent_team derived from MATCHUP)
  - Migration 0005 creating nba_player_gamelogs with 3 composite indexes
  - PlayerStat.opponent_team and PlayerStat.home_away nullable columns for NFL conditional queries
  - ingest_nba_gamelogs_season() bulk pipeline via PlayerGameLogs endpoint
  - Wave 0 test stubs for SC-1 (GREEN) and SC-2 (xfail pending Plan 03)

affects:
  - 18-02 (NBA situational query builders depend on nba_player_gamelogs table)
  - 18-03 (NFL conditional queries depend on player_stats.opponent_team/home_away)

tech-stack:
  added: []
  patterns:
    - "PlayerGameLogs bulk endpoint: one HTTP call per season fetches all player game rows"
    - "MATCHUP '@' detection for is_home derivation; regex split for opponent_team"
    - "Module-level nba_api import for unittest.mock patchability (Phase 8 locked pattern)"
    - "Lazy get_sync_engine import inside main() only to avoid import-time DB connection"

key-files:
  created:
    - src/sportsbet/ingestion/nba_gamelogs.py
    - alembic/versions/0005_add_gamelog_schema.py
    - tests/test_nba_gamelogs_schema.py
    - tests/test_nba_gamelogs_ingest.py
    - tests/test_gamelog_injury_join.py
  modified:
    - src/sportsbet/db/models.py

key-decisions:
  - "NBAPlayerGameLog uses Integer (not String) for player_id — matches nba_api NBA player IDs which are integers"
  - "is_home/opponent_team derived at ingest from MATCHUP column — eliminates need for separate game metadata join"
  - "PlayerStat opponent_team/home_away are nullable — existing rows have no data; only populated on new ingest"
  - "Migration 0005 hand-written following Phase 1 locked decision — autogenerate omits composite indexes"
  - "xfail(strict=False) on SC-2 stubs — Plan 03 implements query builders; xpass when they exist"

patterns-established:
  - "MATCHUP parsing: ~df['MATCHUP'].str.contains('@') for is_home; split on ' @ | vs\\.' for opponent_team"
  - "Wave 0 TDD pattern: pytest.importorskip() for modules pending future tasks; xfail for future plans"

requirements-completed: [SC-1, SC-2]

duration: 7min
completed: 2026-03-25
---

# Phase 18 Plan 01: NBA Gamelog Schema + Ingest Pipeline Summary

**nba_player_gamelogs table with MATCHUP-derived is_home/opponent_team, migration 0005, and PlayerGameLogs bulk ingest pipeline powering Phase 18 situational conditional prop queries**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-25T18:09:02Z
- **Completed:** 2026-03-25T18:16:00Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- NBAPlayerGameLog ORM model with 15 per-game columns including is_home and opponent_team derived at ingest time from MATCHUP column
- Migration 0005 creates nba_player_gamelogs with composite indexes on (player_id, season), (game_date, season), and (opponent_team, season); extends player_stats with opponent_team + home_away for NFL conditional queries
- ingest_nba_gamelogs_season() pipeline correctly parses MATCHUP ("vs." = home, "@" = away), applies rate limit sleep, and calls gc.collect()
- All 7 SC-1 tests GREEN; 2 SC-2 injury-join stubs xfail pending Plan 03; 170 total tests pass, 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 test stubs (RED phase)** - `9bd0ff3` (test)
2. **Task 2: NBAPlayerGameLog ORM + migration 0005 (GREEN phase)** - `ca061e2` (feat)
3. **Task 3: nba_gamelogs.py ingest pipeline (GREEN phase)** - `de8b7ca` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD tasks had RED commit (Task 1 stubs) followed by GREEN commits (Tasks 2-3 production code)_

## Files Created/Modified
- `src/sportsbet/db/models.py` - Added NBAPlayerGameLog ORM class + opponent_team/home_away to PlayerStat; imported Boolean
- `alembic/versions/0005_add_gamelog_schema.py` - Migration creating nba_player_gamelogs table with 3 indexes + player_stats extensions
- `src/sportsbet/ingestion/nba_gamelogs.py` - PlayerGameLogs bulk ingest with MATCHUP parsing, rate limiting, gc.collect()
- `tests/test_nba_gamelogs_schema.py` - 3 schema tests (NBAPlayerGameLog ORM, PlayerStat columns, required columns)
- `tests/test_nba_gamelogs_ingest.py` - 4 ingest tests (matchup parsing x3, mock ingest e2e)
- `tests/test_gamelog_injury_join.py` - 2 xfail stubs for Plan 03 SQL pattern assertions

## Decisions Made
- NBAPlayerGameLog.player_id uses Integer (not String) — nba_api NBA player IDs are integers, consistent with NBAPlayerStats
- MATCHUP derivation at ingest time eliminates a JOIN on game metadata for every prop query
- xfail(strict=False) on SC-2 stubs because Plan 03 hasn't been executed; tests become xpass when query builders exist
- Followed Phase 8 pattern: PlayerGameLogs imported at module level not inside closure for mock patchability

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. DB migration (alembic upgrade head) needed to apply 0005 to live PostgreSQL instance.

## Next Phase Readiness
- nba_player_gamelogs table and ORM ready for Plan 02 NBA situational query builders
- player_stats.opponent_team/home_away columns ready for Plan 03 NFL conditional filters
- Wave 0 SC-2 stubs in place as contracts for Plan 03 implementation

---
*Phase: 18-situational-game-log-prop-queries*
*Completed: 2026-03-25*
