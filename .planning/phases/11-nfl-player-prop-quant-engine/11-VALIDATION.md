---
phase: 11
slug: nfl-player-prop-quant-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
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
| 11-01-01 | 01 | 0 | PROP-03 | unit | `pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x --tb=short` | ❌ W0 | ⬜ pending |
| 11-01-02 | 01 | 1 | PROP-03 | unit | `pytest tests/test_prop_query_builder.py::test_invalid_prop_type_rejected -x` | ❌ W0 | ⬜ pending |
| 11-01-03 | 01 | 1 | PROP-03 | unit | `pytest tests/test_prop_query_builder.py::test_parameterized_sql -x` | ❌ W0 | ⬜ pending |
| 11-01-04 | 01 | 1 | PROP-03 | unit | `pytest tests/test_prop_executor.py::test_adequate_sample -x` | ❌ W0 | ⬜ pending |
| 11-01-05 | 01 | 1 | PROP-03 | unit | `pytest tests/test_prop_executor.py::test_insufficient_sample -x` | ❌ W0 | ⬜ pending |
| 11-01-06 | 01 | 1 | PROP-03 | integration | `pytest tests/test_prop_executor.py::test_live_db -x` (skipif no DB) | ❌ W0 | ⬜ pending |
| 11-02-01 | 02 | 2 | PROP-04 | unit | `pytest tests/test_prop_executor.py::test_kinematic_adjustment_applied -x` | ❌ W0 | ⬜ pending |
| 11-02-02 | 02 | 2 | PROP-04 | unit | `pytest tests/test_prop_executor.py::test_kinematic_no_adjust_pass_prop -x` | ❌ W0 | ⬜ pending |
| 11-02-03 | 02 | 2 | PROP-04 | unit | `pytest tests/test_prop_executor.py::test_kinematic_probability_clamped -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_prop_query_builder.py` — stubs for PROP-03 (SQL gate, parameterization, filter allowlist)
- [ ] `tests/test_prop_executor.py` — stubs for PROP-03 (adequate/insufficient sample, Decimal wrapping) and PROP-04 (kinematic adjustment)
- [ ] `src/sportsbet/prop/__init__.py` — new subpackage marker
- [ ] `src/sportsbet/prop/query_builder.py` — PropQueryBuilder stub
- [ ] `src/sportsbet/prop/executor.py` — run_prop_query stub
- [ ] `src/sportsbet/prop/agents.py` — make_prop_quant_agent stub

*Existing `tests/test_prop_models.py` covers PropParams/PropResult — already 5/5 green, no changes needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Kinematic boost magnitude is reasonable | PROP-04 | Heuristic value (5pp) requires human judgment | Run `PropQuantAgent` for a WR with known NGS data; verify `true_probability` shifts by ~0.05 when `geometric_mismatch_flag=True` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
