---
phase: 9
slug: critical-pipeline-gap-closure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ with pytest-asyncio |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_quant.py tests/test_context.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_quant.py tests/test_context.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 9-01-01 | 01 | 0 | CTXT-02 | unit | `pytest tests/test_context.py::test_context_agent_rejects_stale_odds -x` | ❌ W0 | ⬜ pending |
| 9-01-02 | 01 | 0 | DATA-03 | unit | `pytest tests/test_context.py::test_context_agent_persists_odds_snapshot -x` | ✅ (update assertion) | ⬜ pending |
| 9-01-03 | 01 | 1 | QUANT-03 | integration | `pytest tests/test_quant.py::test_run_quant_query_passing -x` | ✅ (fix target) | ⬜ pending |
| 9-01-04 | 01 | 1 | QUANT-01 | unit | `pytest tests/test_quant.py::test_run_quant_query_mock_adequate_sample -x` | ✅ | ⬜ pending |
| 9-01-05 | 01 | 1 | ARBT-01 | integration | `pytest tests/test_quant.py::test_quant_agent_live -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_context.py::test_context_agent_rejects_stale_odds` — new test stub for CTXT-02 wiring (stale odds rejected in `make_context_agent`)
- [ ] `tests/test_context.py::test_context_agent_persists_odds_snapshot` — update existing test assertion from `price is None` to `price is not None` for DATA-03 fix

*Existing infrastructure (`pytest`, `pytest-asyncio`) covers all other phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `alembic upgrade head` runs without error after 0003 migration added | QUANT-03 | Requires live DB connection | Run `alembic upgrade head` against local PostgreSQL; confirm no error and `\d play_by_play` shows `air_yards`, `two_point_attempt`, `complete_pass` columns |
| PBP re-ingestion populates new columns with non-NULL values | QUANT-03 | Requires live nflreadpy data load | After migration, run ingestion for one season; query `SELECT COUNT(*) FROM play_by_play WHERE air_yards IS NOT NULL` — must be > 0 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
