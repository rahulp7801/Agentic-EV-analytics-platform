---
phase: 12-nba-player-prop-quant-engine
plan: "01"
subsystem: database
tags: [asyncpg, pydantic, nba, normaldist, tdd, player-props, sql]

# Dependency graph
requires:
  - phase: 11-nfl-player-prop-quant-engine
    provides: PropQueryBuilder pattern, PropParams/PropResult models, executor pattern with MIN_SAMPLE gate
  - phase: 10-player-prop-and-nba-data-layer
    provides: nba_player_stats table schema (season totals, player_id INTEGER, games_played)

provides:
  - NBAQueryBuilder: parameterized SQL dispatch for nba_player_stats with pra/double_double/single-stat templates
  - run_nba_prop_query: async executor with NormalDist CDF probability model (not frequency count)
  - double_double added to PropParams.prop_type Literal union
  - NBA_PROP_COLUMN_MAP, NBA_PROP_CV_MAP, PACE_ADJUSTED_PROPS constants for Plan 02

affects:
  - 12-02-PLAN (NBAQuantAgent closure using run_nba_prop_query)

# Tech tracking
tech-stack:
  added: [statistics.NormalDist (stdlib — no scipy dependency)]
  patterns:
    - NormalDist CDF for season-aggregate NBA data (not frequency count like NFL)
    - Coefficient of Variation (CV) heuristic std estimation per prop type
    - Inclusion-exclusion for double_double probability (P(pts>=10)*P(reb>=10) + P(pts)*P(ast) + P(reb)*P(ast) - 2*all_three)
    - std floor of 0.5 prevents StatisticsError when avg_per_game=0.0

key-files:
  created:
    - src/sportsbet/prop/nba_query_builder.py
    - src/sportsbet/prop/nba_executor.py
    - tests/test_nba_prop_query_builder.py
    - tests/test_nba_prop_executor.py
  modified:
    - src/sportsbet/graph/models.py
    - src/sportsbet/prop/query_builder.py

key-decisions:
  - "NBAQueryBuilder dispatches pra->_NBA_PRA_TEMPLATE, double_double->_NBA_DD_TEMPLATE, single->_NBA_SINGLE_STAT_TEMPLATE"
  - "player_id cast to int() in NBAQueryBuilder.build() — nba_player_stats.player_id is INTEGER not VARCHAR"
  - "NormalDist CDF probability model for NBA (not Wilson CI frequency count) — season-aggregate data has no per-game binary outcomes"
  - "std = max(0.5, avg_per_game * CV_MAP[prop_type]) — 0.5 floor prevents StatisticsError when avg=0"
  - "MIN_SAMPLE_GAMES=20 for NBA (games threshold, not weeks like NFL's 30)"
  - "confidence_interval=None for NBA props — Wilson CI not applicable to season-aggregate data"
  - "double_double uses independence assumption for inclusion-exclusion — documented as v1 heuristic"
  - "LEAGUE_AVG_PACE, LEAGUE_AVG_DEF_RATING, REST_PENALTY, HOME_BOOST constants exported from nba_executor.py for Plan 02 import stability"

patterns-established:
  - "NBA probability model: NormalDist(avg_per_game, max(0.5, avg*CV)).cdf(line) gives P(under); 1-cdf gives P(over)"
  - "Decimal wrapping: Decimal(str(round(x, 6))) for all float->Decimal conversions; never assign float to strict Pydantic Decimal field"
  - "SQL template dispatch by prop_type: special composite templates before single-stat fallback"

requirements-completed: [PROP-05]

# Metrics
duration: 5min
completed: 2026-03-22
---

# Phase 12 Plan 01: NBA Query Builder and Executor Summary

**NBAQueryBuilder + run_nba_prop_query with NormalDist CDF probability model, CV-estimated std, double_double inclusion-exclusion, and PropParams extended with double_double Literal**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-23T02:22:17Z
- **Completed:** 2026-03-23T02:27:00Z
- **Tasks:** 3 (RED-RED-GREEN TDD cycle)
- **Files modified:** 6

## Accomplishments

- NBAQueryBuilder with three SQL template dispatch paths: single-stat, PRA composite, double_double DD template; player_id cast to int for INTEGER column compatibility
- run_nba_prop_query using statistics.NormalDist CDF over per-game averages from season totals; MIN_SAMPLE_GAMES=20 gate; std floor prevents StatisticsError; double_double via inclusion-exclusion
- PropParams.prop_type Literal extended with "double_double" (backward-compatible); PROP_COLUMN_MAP in query_builder.py gets NBA forward-compat entry

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — NBA query builder tests** - `cac5a43` (test)
2. **Task 2: RED — NBA executor tests** - `99e8436` (test)
3. **Task 3: GREEN — NBAQueryBuilder, run_nba_prop_query, PropParams** - `d3c2a6f` (feat)

_TDD cycle: RED (Tasks 1-2) then GREEN (Task 3)_

## Files Created/Modified

- `src/sportsbet/prop/nba_query_builder.py` - NBAQueryBuilder class with three SQL templates, NBA_PROP_COLUMN_MAP, NBA_PROP_CV_MAP, PACE_ADJUSTED_PROPS
- `src/sportsbet/prop/nba_executor.py` - run_nba_prop_query async function, MIN_SAMPLE_GAMES=20, NormalDist CDF model, _double_double_prob inclusion-exclusion, Plan 02 placeholder constants
- `tests/test_nba_prop_query_builder.py` - 7 TDD tests: build dispatch, SQL injection prevention, player_id int cast
- `tests/test_nba_prop_executor.py` - 7 TDD tests: insufficient sample gate, Decimal wrapping, std floor, double_double probability
- `src/sportsbet/graph/models.py` - PropParams.prop_type Literal extended with "double_double"
- `src/sportsbet/prop/query_builder.py` - PROP_COLUMN_MAP gets "double_double" entry with NBA forward-compat comment

## Decisions Made

- NormalDist CDF (not Wilson CI frequency count) — NBA season-aggregate data has one row per player per season; no per-game binary outcomes available for proportion-based CI
- std floor of 0.5 is set as a hard lower bound in both `_norm_cdf_over` and `_double_double_prob` — tested explicitly for avg=0.0 case
- Independence assumption for double_double inclusion-exclusion is documented as v1 heuristic — correlation modeling deferred to v2
- LEAGUE_AVG_PACE/DEF_RATING/REST_PENALTY/HOME_BOOST exported from nba_executor.py at definition time so Plan 02 NBAQuantAgent can import without modifying nba_executor.py

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- NBAQueryBuilder and run_nba_prop_query are ready for Plan 02 NBAQuantAgent closure wiring
- PACE_ADJUSTED_PROPS frozenset and Plan 02 placeholder constants (LEAGUE_AVG_PACE, REST_PENALTY, HOME_BOOST) exported for direct import
- Full 129-test suite passes; no regressions from PropParams Literal extension

---
*Phase: 12-nba-player-prop-quant-engine*
*Completed: 2026-03-22*
