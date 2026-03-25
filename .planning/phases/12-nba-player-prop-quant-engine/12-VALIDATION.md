---
phase: 12
slug: nba-player-prop-quant-engine
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-22
updated: 2026-03-24
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ with pytest-asyncio |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| **Quick run command** | `pytest tests/test_nba_prop_query_builder.py tests/test_nba_prop_executor.py -x --tb=short` |
| **Full suite command** | `pytest tests/ -x --tb=short` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_nba_prop_query_builder.py tests/test_nba_prop_executor.py -x --tb=short`
- **After every plan wave:** Run `pytest tests/ -x --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | PROP-05 | unit | `pytest tests/test_nba_prop_query_builder.py -x --tb=short` | ✅ | ✅ green |
| 12-01-02 | 01 | 1 | PROP-05, NBA-02 | unit | `pytest tests/test_nba_prop_executor.py -x --tb=short` | ✅ | ✅ green |
| 12-02-01 | 02 | 2 | NBA-02 | unit | `pytest tests/test_nba_prop_executor.py::test_rest_penalty_applied tests/test_nba_prop_executor.py::test_pace_adjustment_up -x --tb=short` | ✅ | ✅ green |
| 12-02-02 | 02 | 2 | NBA-02 | unit | `pytest tests/ -x --tb=short` | ✅ | ✅ green |

*Note: `test_live_db` in `test_nba_prop_executor.py` is DB-gated (skipif no `SPORTSBET_TEST_DATABASE_URL`) — counted in the 11 skipped-DB, not marked green.*

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_nba_prop_query_builder.py` — stubs for PROP-05 (SQL gate, parameterization, PRA/DD templates, player_id int cast)
- [x] `tests/test_nba_prop_executor.py` — stubs for PROP-05 (adequate/insufficient sample, Decimal wrapping) and NBA-02 (pace, def_rating, rest penalty, home boost, clamping)
- [x] `tests/test_prop_models.py` — add `test_double_double_prop_type` stub after model update

*Existing infrastructure (pytest, asyncpg, pydantic) covers all phase requirements — no new framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live PostgreSQL integration | PROP-05 | Requires DB connection | `pytest tests/test_nba_prop_executor.py::test_live_db -x` (skipif no DB env var) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
