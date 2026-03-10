---
phase: 1
slug: data-foundation
status: active
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-10
updated: 2026-03-10
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 8.2 + pytest-asyncio >= 0.23 + pytest-postgresql |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — Wave 0 installs |
| **Quick run command** | `pytest tests/ -x -q --tb=short` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds (excluding live data download) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | DATA-04 | integration | `pytest tests/test_migrations.py::test_alembic_upgrade_clean -x` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 0 | DATA-04 | integration | `pytest tests/test_migrations.py::test_alembic_downgrade_clean -x` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | DATA-01 | integration | `pytest tests/test_schema.py::test_pbp_indexes -x` | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 1 | DATA-01 | integration | `pytest tests/test_schema.py::test_explain_no_seq_scan -x` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 1 | DATA-03 | integration | `pytest tests/test_schema.py::test_odds_snapshot_write_read -x` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 2 | DATA-02 | unit | `pytest tests/test_ingestion.py::test_pbp_column_whitelist -x` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 2 | DATA-02 | integration | `pytest tests/test_ingestion.py::test_pbp_multiseason_load -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/conftest.py` — shared fixtures: SQLAlchemy engine, alembic_cfg; skips gracefully without DB
- [x] `tests/test_schema.py` — promoted to real assertions for DATA-01, DATA-03: index existence, EXPLAIN ANALYZE, odds_snapshot read/write
- [x] `tests/test_migrations.py` — promoted to real assertions for DATA-04: alembic upgrade head + downgrade base; skipif without SPORTSBET_TEST_DATABASE_URL
- [x] `tests/test_ingestion.py` — stubs for DATA-02: column whitelist unit test, year-by-year loop integration test (xfail, pending Plan 03)
- [x] `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`, `pythonpath = ["src"]`, `serial` marker registered
- [x] Framework install: pytest, pytest-asyncio, alembic, sqlalchemy, asyncpg, psycopg installed

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 5+ seasons load without OOM crash | DATA-02 | Requires GB-scale download from nflreadpy parquet cache; too slow for CI | Run `python -m sportsbet.ingestion.pbp --seasons 2019 2020 2021 2022 2023`; confirm no MemoryError; check psutil log output shows gc.collect() called per season |
| Alembic upgrade on fresh PostgreSQL | DATA-04 | Requires a clean DB instance, not ephemeral fixture | `dropdb sportsbet_test && createdb sportsbet_test && alembic upgrade head`; confirm all tables and indexes exist via `\d` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Wave 0 (Plan 01-01) and Wave 1 (Plan 01-02) complete. All test infrastructure and schema migration in place.
