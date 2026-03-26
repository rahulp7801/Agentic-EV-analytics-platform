---
phase: 22-tech-debt-cleanup
plan: "01"
subsystem: ingestion, prop-agent, test-suite
tags: [tech-debt, idempotency, deprecation, observability, docstring]
dependency_graph:
  requires: []
  provides:
    - PBP ingest is idempotent (on_conflict_do_nothing)
    - Zero DeprecationWarnings in test_graph.py and test_quant.py under -W error
    - prop/agents.py docstring is accurate (no TODO placeholder)
    - WARNING logged when kinematic_result is None for receiving props
  affects:
    - src/sportsbet/ingestion/pbp.py
    - src/sportsbet/prop/agents.py
    - tests/test_graph.py
tech_stack:
  added: []
  patterns:
    - pg_insert().on_conflict_do_nothing(index_elements=[...]) for idempotent bulk writes
    - structlog.testing.capture_logs() for asserting log events in tests
    - datetime.now(timezone.utc) replaces deprecated datetime.utcnow()
key_files:
  created:
    - tests/test_pbp_idempotency.py
    - tests/test_prop_quant_warning.py
  modified:
    - src/sportsbet/ingestion/pbp.py
    - tests/test_graph.py
    - src/sportsbet/prop/agents.py
decisions:
  - "pg_insert(PlayByPlay).on_conflict_do_nothing(index_elements=['game_id','play_id']) — NULL game_id rows are a known v1 limitation (PostgreSQL treats NULL != NULL in unique indexes)"
  - "log.warning('prop_quant_agent_kinematic_missing') placed after kinematic_result extraction, before _apply_kinematic_adjustment — observable signal for PROP-04 two-invocation contract violations"
  - "datetime.now(timezone.utc) used (not datetime.UTC) — consistent with line 27 of test_graph.py per RESEARCH.md Pitfall 2"
metrics:
  duration: 6 minutes
  completed_date: "2026-03-26"
  tasks: 3
  files: 5
---

# Phase 22 Plan 01: Tech Debt Cleanup (SC-1 through SC-4) Summary

Four discrete tech debt items fixed: PBP idempotency via PostgreSQL `ON CONFLICT DO NOTHING`, Python 3.12 `datetime.utcnow()` deprecation removed, stale Phase-11 TODO placeholder docstring replaced with accurate PROP-04 description, and missing structlog WARNING added for None kinematic context on receiving props.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Wave 0 RED test stubs | f58531f | tests/test_pbp_idempotency.py, tests/test_prop_quant_warning.py |
| 2 | PBP idempotency + datetime deprecation fix | a79404d | src/sportsbet/ingestion/pbp.py, tests/test_graph.py |
| 3 | Stale docstring removal + PROP-04 kinematic warning | 33bd1e3 | src/sportsbet/prop/agents.py |

## Success Criteria Verification

- SC-1: `pytest tests/test_pbp_idempotency.py` — PASSED
- SC-2: `pytest tests/test_graph.py tests/test_quant.py -W error::DeprecationWarning` — PASSED (0 warnings)
- SC-3: `python -c "assert 'TODO placeholder' not in pathlib.Path('...agents.py').read_text()"` — OK
- SC-4: `pytest tests/test_prop_quant_warning.py` — PASSED
- Full suite: `pytest tests/ -q` — 206 passed, 11 skipped, 2 xfailed

## Key Changes

**src/sportsbet/ingestion/pbp.py:**
- Added imports: `from sqlalchemy.dialects.postgresql import insert as pg_insert` and `from sportsbet.db.models import PlayByPlay`
- Replaced `df_pd.to_sql(...)` with chunked `engine.begin() / conn.execute(pg_insert(PlayByPlay).on_conflict_do_nothing(index_elements=["game_id", "play_id"]), rows[i:i+CHUNK])`
- Updated comment to document the NULL game_id v1 limitation

**tests/test_graph.py:**
- Line 200: `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` — eliminates Python 3.12 DeprecationWarning

**src/sportsbet/prop/agents.py:**
- Module docstring: replaced stale Phase-11 TODO placeholder language with accurate PROP-04 description including kinematic observability contract
- Added 6-line warning block: `if kinematic_result is None and params.prop_type in RECEIVING_PROPS: log.warning("prop_quant_agent_kinematic_missing", ...)`

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

**Note on test_pbp_idempotency.py design:** The test uses MagicMock for the SQLAlchemy engine throughout (both `to_sql` and `on_conflict` paths), which means it does not simulate IntegrityError from a real DB. The test's value is verifying the structural interface — that `engine.begin()` is called as a context manager and `conn.execute()` receives the `on_conflict_do_nothing` insert statement. A real DB integration test would require `SPORTSBET_TEST_DATABASE_URL` and is deferred (consistent with Phase 1 locked pattern for skipif DB tests).

## Self-Check: PASSED

- FOUND: tests/test_pbp_idempotency.py
- FOUND: tests/test_prop_quant_warning.py
- FOUND: src/sportsbet/ingestion/pbp.py (on_conflict_do_nothing present: 1 occurrence)
- FOUND: src/sportsbet/prop/agents.py (prop_quant_agent_kinematic_missing present: 1 occurrence)
- FOUND commit f58531f (Task 1 RED stubs)
- FOUND commit a79404d (Task 2 implementation)
- FOUND commit 33bd1e3 (Task 3 implementation)
