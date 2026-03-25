---
phase: 11
slug: nfl-player-prop-quant-engine
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-22
updated: 2026-03-24
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ with pytest-asyncio |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| **Quick run command** | `pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x --tb=short` |
| **Full suite command** | `pytest tests/ -x --tb=short` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x --tb=short`
- **After every plan wave:** Run `pytest tests/ -x --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 0 | PROP-03 | unit | `pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x --tb=short` | ✅ | ✅ green |
| 11-01-02 | 01 | 1 | PROP-03 | unit | `pytest tests/test_prop_query_builder.py::test_invalid_prop_type_rejected -x` | ✅ | ✅ green |
| 11-01-03 | 01 | 1 | PROP-03 | unit | `pytest tests/test_prop_query_builder.py::test_parameterized_sql -x` | ✅ | ✅ green |
| 11-01-04 | 01 | 1 | PROP-03 | unit | `pytest tests/test_prop_executor.py::test_adequate_sample -x` | ✅ | ✅ green |
| 11-01-05 | 01 | 1 | PROP-03 | unit | `pytest tests/test_prop_executor.py::test_insufficient_sample -x` | ✅ | ✅ green |
| 11-01-06 | 01 | 1 | PROP-03 | integration | `pytest tests/test_prop_executor.py::test_live_db -x` (skipif no DB) | ✅ | ⬜ pending (skipif DB) |
| 11-02-01 | 02 | 2 | PROP-04 | unit | `pytest tests/test_prop_executor.py::test_kinematic_adjustment_applied -x` | ✅ | ✅ green |
| 11-02-02 | 02 | 2 | PROP-04 | unit | `pytest tests/test_prop_executor.py::test_kinematic_no_adjust_pass_prop -x` | ✅ | ✅ green |
| 11-02-03 | 02 | 2 | PROP-04 | unit | `pytest tests/test_prop_executor.py::test_kinematic_probability_clamped -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_prop_query_builder.py` — stubs for PROP-03 (SQL gate, parameterization, filter allowlist)
- [x] `tests/test_prop_executor.py` — stubs for PROP-03 (adequate/insufficient sample, Decimal wrapping) and PROP-04 (kinematic adjustment)
- [x] `src/sportsbet/prop/__init__.py` — new subpackage marker
- [x] `src/sportsbet/prop/query_builder.py` — PropQueryBuilder stub
- [x] `src/sportsbet/prop/executor.py` — run_prop_query stub
- [x] `src/sportsbet/prop/agents.py` — make_prop_quant_agent stub

*Existing `tests/test_prop_models.py` covers PropParams/PropResult — already 5/5 green, no changes needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Kinematic boost magnitude is reasonable | PROP-04 | Heuristic value (5pp) requires human judgment | Run `PropQuantAgent` for a WR with known NGS data; verify `true_probability` shifts by ~0.05 when `geometric_mismatch_flag=True` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
