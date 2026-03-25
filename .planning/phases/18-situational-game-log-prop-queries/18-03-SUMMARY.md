---
phase: 18-situational-game-log-prop-queries
plan: 03
subsystem: database
tags: [sql, asyncpg, statsmodels, wilson-ci, nba, nfl, props, query-builder, executor]

# Dependency graph
requires:
  - phase: 18-01
    provides: nba_player_gamelogs schema, player_stats.opponent_team/home_away columns, migration 0005
  - phase: 18-02
    provides: PropParams situational fields (opponent_team, home_away, last_n_games, teammate_out)
provides:
  - PropQueryBuilder NFL situational WHERE clause construction (opponent_team, home_away, teammate_out INTERVAL, last_n_games LIMIT subquery)
  - NFL_SITUATIONAL_ALLOWED_KEYS frozenset (SQL injection prevention for situational column names)
  - NBAQueryBuilder conditional dispatch to nba_player_gamelogs templates (binary frequency path)
  - NBA_GAMELOG_COLUMN_MAP + _NBA_GAMELOG_SINGLE_TEMPLATE + _NBA_GAMELOG_PRA_TEMPLATE
  - executor.py Wilson CI widening for conditional small samples (is_conditional gate)
  - nba_executor.py run_nba_gamelog_query (Wilson CI binary frequency) + conditional dispatch in run_nba_prop_query
  - 9 SC-4/SC-5 tests all GREEN
affects:
  - prop-quant-agent
  - nba-prop-quant-agent
  - context-agent (situational_params feeds directly into query builder)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Conditional SQL dispatch: is_conditional() helper gates gamelog vs season-aggregate path
    - Situational clause append order: opponent_team -> home_away -> teammate_out -> last_n_games (ORDER BY semantics preserved)
    - Wilson CI total==0 guard before proportion_confint (NaN prevention)
    - conditional_small_sample data_source tag for downstream Kelly Criterion awareness
    - NBA gamelog is_home Boolean conversion: "home" -> True, "away" -> False at build() time

key-files:
  created:
    - tests/test_prop_query_builder_situational.py
    - tests/test_executor_small_sample.py
  modified:
    - src/sportsbet/prop/query_builder.py
    - src/sportsbet/prop/nba_query_builder.py
    - src/sportsbet/prop/executor.py
    - src/sportsbet/prop/nba_executor.py

key-decisions:
  - "NFL_SITUATIONAL_ALLOWED_KEYS frozenset guards opponent_team and home_away column names; values always in positional $N args"
  - "last_n_games applied LAST in append order so subquery narrows to most-recent N games that already pass opponent/location filters"
  - "(season, week) IN subquery for NFL last_n_games — not game_id IN — because existing player_stats rows have NULL game_id (migration 0005)"
  - "teammate_out uses INTERVAL date-window approximation on injury_reports (scraped_at BETWEEN game_date-2days AND game_date+1day) because injury_reports.game_id is nullable"
  - "NBA gamelog home_away converts string Literal to Boolean at NBAQueryBuilder.build() time (nba_player_gamelogs.is_home is BOOLEAN not string)"
  - "double_double excluded from NBA gamelog path — no per-game composite binary model in v1; falls through to season-aggregate NormalDist"
  - "executor.py conditional gate: total==0 always insufficient_sample; is_conditional + total<30 returns conditional_small_sample with wide CI; unconditional total<30 still returns insufficient_sample (existing behavior preserved)"

patterns-established:
  - "Situational WHERE clause security invariant: column names from static frozenset allowlists, values always in positional $N args"
  - "Wilson CI NaN guard: total==0 short-circuits before proportion_confint; math.isnan(lo/hi) secondary guard for nobs=1 edge"
  - "conditional_small_sample data_source string: callers (Kelly sizing) inspect this to apply conservative multipliers on wide CI results"

requirements-completed:
  - SC-2
  - SC-4
  - SC-5

# Metrics
duration: 11min
completed: 2026-03-25
---

# Phase 18 Plan 03: Situational Query Builders + Wilson CI Widening Summary

**PropQueryBuilder and NBAQueryBuilder extended with situational WHERE clauses (opponent_team, home_away, teammate_out INTERVAL, last_n_games subquery) using positional $N params; executor Wilson CI widening removes hard MIN gate for conditional small samples; 9 new SC-4/SC-5 tests all GREEN.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-25T18:24:47Z
- **Completed:** 2026-03-25T18:35:57Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- NFL PropQueryBuilder: 4 new situational filter clauses (opponent_team, home_away, teammate_out INTERVAL date-window, last_n_games LIMIT subquery) with positional params and NFL_SITUATIONAL_ALLOWED_KEYS frozenset
- NBAQueryBuilder: conditional dispatch to nba_player_gamelogs templates (SINGLE + PRA) with opponent_team, is_home, last_n_games LIMIT filters; double_double falls through to season-aggregate path
- executor.py: is_conditional gate allows conditional small samples to receive wide Wilson CI instead of insufficient_sample rejection; total==0 always guards; conditional_small_sample tag for downstream consumers
- nba_executor.py: run_nba_gamelog_query (Wilson CI binary frequency path); run_nba_prop_query delegates to it when any situational filter set

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 test stubs for SC-4 and SC-5** - `e1e4e63` (test)
2. **Task 2: PropQueryBuilder NFL situational WHERE clause construction** - `6f448f5` (feat)
3. **Task 3: NBAQueryBuilder gamelog dispatch + executor Wilson CI widening** - `64d120a` (feat)

## Files Created/Modified

- `tests/test_prop_query_builder_situational.py` - 7 SC-4 tests for NFL/NBA situational WHERE construction
- `tests/test_executor_small_sample.py` - 2 SC-5 tests for Wilson CI pattern and total=0 gate
- `src/sportsbet/prop/query_builder.py` - NFL_SITUATIONAL_ALLOWED_KEYS frozenset; opponent_team, home_away, teammate_out INTERVAL, last_n_games subquery clauses
- `src/sportsbet/prop/nba_query_builder.py` - NBA_GAMELOG_COLUMN_MAP; gamelog templates; _is_conditional() helper; conditional dispatch in build()
- `src/sportsbet/prop/executor.py` - is_conditional gate; total==0 guard; NaN guard; conditional_small_sample tag
- `src/sportsbet/prop/nba_executor.py` - run_nba_gamelog_query (Wilson CI); conditional dispatch in run_nba_prop_query

## Decisions Made

- NFL last_n_games uses `(season, week) IN (SELECT ...)` subquery rather than `game_id IN (...)` because existing `player_stats` rows have NULL `game_id` (added as nullable in migration 0005). The (season, week) tuple is the stable composite key.
- teammate_out uses INTERVAL date-window on `injury_reports.scraped_at` rather than a direct `game_id` join because `injury_reports.game_id` is nullable in v1 schema. The [-2 days, +1 day] window is the v1 approximation (documented in RESEARCH.md Pitfall 4).
- NBA gamelog `is_home` column is BOOLEAN (not string). The `"home"/"away"` Literal in PropParams is converted to `True/False` at `NBAQueryBuilder.build()` time — not at executor time.
- `double_double` excluded from NBA gamelog path: no per-game composite binary model in v1. It always falls through to the season-aggregate NormalDist + inclusion-exclusion path.
- The unconditional `total < MIN_PROP_SAMPLE_SIZE` gate is preserved exactly — only the conditional path gets Wilson CI widening (SC-5 requirement).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all three tasks executed cleanly. The xfail tests in `test_gamelog_injury_join.py` remain XFAIL because they import from `sportsbet.prop.gamelog_query_builder` (a different module path than what Plan 03 builds). Those tests use `pytest.xfail()` inside ImportError handler with `strict=False` so they do not constitute failures. The INTERVAL requirement they test is fully satisfied by `test_teammate_out_uses_date_window_not_game_id_join` which is GREEN.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 18 is complete: all SC-1 through SC-5 tests pass (25 of 27 collected, 2 are pre-existing xfail stubs)
- The full conditional query pipeline is wired: PropParams situational fields -> query builders -> executors -> PropResult with conditional_small_sample tagging
- Downstream consumers (Kelly Criterion sizing, EV calculation) can inspect `PropResult.data_source == "conditional_small_sample"` to apply conservative confidence multipliers
- No blockers for future phases

## Self-Check: PASSED

- SUMMARY.md: FOUND
- query_builder.py: FOUND
- nba_query_builder.py: FOUND
- executor.py: FOUND
- nba_executor.py: FOUND
- Commit e1e4e63 (Task 1): FOUND
- Commit 6f448f5 (Task 2): FOUND
- Commit 64d120a (Task 3): FOUND

---
*Phase: 18-situational-game-log-prop-queries*
*Completed: 2026-03-25*
