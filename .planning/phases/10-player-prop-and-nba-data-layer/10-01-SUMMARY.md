---
phase: 10-player-prop-and-nba-data-layer
plan: "01"
subsystem: data-layer
tags:
  - player-props
  - nba
  - orm
  - pydantic
  - alembic
  - odds-api
dependency_graph:
  requires:
    - "Phase 04: OddsAPIPoller (odds_poller.py) — extended with fetch_player_props()"
    - "Phase 01: Alembic migration chain (0003_add_pbp_quant_columns down_revision)"
  provides:
    - "PlayerPropSnapshot ORM table with 3 composite indexes"
    - "NBAPlayerStats ORM table with UniqueConstraint + 4 indexes"
    - "PropParams / PropResult Pydantic models (Phase 11 contract)"
    - "write_player_prop_snapshot() writer (mirrors write_odds_snapshot() pattern)"
    - "OddsAPIPoller.fetch_player_props() two-step event-list + per-event fetch"
  affects:
    - "Phase 11: PropQueryBuilder consumes PropParams"
    - "Phase 13: NBA data ingestion uses NBAPlayerStats ORM"
tech_stack:
  added:
    - "nba_api>=1.11 (pyproject.toml dependency)"
  patterns:
    - "Decimal(str(round(raw_prob, 6))) for implied_probability — float-to-Decimal precision pattern"
    - "ConfigDict(strict=True) on all Pydantic I/O models"
    - "BudgetExhaustedError guard at <10 credits before each per-event fetch"
    - "Append-only table pattern (player_prop_snapshots) — no UPDATE/UPSERT"
key_files:
  created:
    - src/sportsbet/ingestion/prop_odds.py
    - alembic/versions/0004_add_prop_and_nba_tables.py
    - tests/test_prop_models.py
    - tests/test_prop_odds.py
  modified:
    - src/sportsbet/db/models.py
    - src/sportsbet/graph/models.py
    - src/sportsbet/ingestion/odds_poller.py
    - tests/test_migrations.py
    - pyproject.toml
decisions:
  - "PropParams.season ge=2000 (not ge=1999): NBA data boundary — earliest reliable NBA stats start 2000 season"
  - "BudgetExhaustedError threshold <10 (not <1) in fetch_player_props(): two-step fetch consumes 2+ credits; 10-credit buffer prevents mid-batch exhaustion"
  - "NBA_PROP_MARKETS includes player_points_rebounds_assists for PRA prop type — maps to PropParams prop_type='pra'"
  - "NBAPlayerStats indexes match Phase 11 query patterns: player timeline (player_id, season), full-season scan (season), team roster (team_id, season)"
  - "Migration 0004 in same file for both tables — single atomic upgrade/downgrade, no partial schema states"
metrics:
  duration: "4 min"
  completed: "2026-03-22"
  tasks_completed: 3
  files_modified: 9
requirements-completed: [PROP-01, PROP-02]
---

# Phase 10 Plan 01: Player Prop Data Layer Summary

**One-liner:** PlayerPropSnapshot + NBAPlayerStats ORM tables with Alembic migration, fetch_player_props() two-step odds fetch, PropParams/PropResult Pydantic gate for Phase 11 prop quant engine.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Wave 0 — TDD RED stubs + pyproject dep + migration 0004 | af43537 | tests/test_prop_models.py, tests/test_prop_odds.py, alembic/versions/0004_add_prop_and_nba_tables.py, pyproject.toml |
| 2 | ORM models + PropParams/PropResult + prop_odds writer + OddsAPIPoller extension | 7eefd1e | src/sportsbet/db/models.py, src/sportsbet/graph/models.py, src/sportsbet/ingestion/prop_odds.py, src/sportsbet/ingestion/odds_poller.py |
| 3 | Migration smoke test + full suite green | 0e556db | tests/test_migrations.py |

## Verification Results

- `pytest tests/test_prop_models.py tests/test_prop_odds.py -x` — 5 passed
- `pytest tests/` — 101 passed, 10 skipped, 0 failures
- `grep "down_revision" alembic/versions/0004_add_prop_and_nba_tables.py` — `"0003_add_pbp_quant_columns"` confirmed
- `grep "class PropParams" src/sportsbet/graph/models.py` — present
- `grep "class PlayerPropSnapshot\|class NBAPlayerStats" src/sportsbet/db/models.py` — both present

## Must-Have Truth Verification

| Truth | Status |
|-------|--------|
| PropParams rejects malformed inputs (invalid prop_type, out-of-range season) with ValidationError | PASS — test_prop_params_invalid_prop_type, test_prop_params_invalid_season |
| PropResult instantiates with all-None fields (stub node compatible) | PASS — test_prop_result_all_nullable |
| PlayerPropSnapshot ORM table with three composite indexes | PASS — ORM class in models.py, migration in 0004 |
| OddsAPIPoller.fetch_player_props() two-step event-list + per-event | PASS — test_fetch_nfl_player_props |
| write_player_prop_snapshot() writes row with non-null implied_probability | PASS — test_write_player_prop_snapshot |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED
