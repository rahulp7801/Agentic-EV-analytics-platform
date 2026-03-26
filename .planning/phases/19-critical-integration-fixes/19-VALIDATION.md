---
phase: 19
slug: critical-integration-fixes
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-25
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_prop_integration_fixes.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds (quick), ~60 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_prop_integration_fixes.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green (188+ passed, 0 new failures)
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 0 | PROP-01 | unit | `python -m pytest tests/test_prop_integration_fixes.py -x -q` | ❌ W0 | ⬜ pending |
| 19-01-02 | 01 | 1 | PROP-01 | unit | `python -m pytest tests/test_prop_integration_fixes.py::test_prop_snapshot_uses_sport_variable_nba -x` | ❌ W0 | ⬜ pending |
| 19-01-03 | 01 | 1 | PROP-01 | unit | `python -m pytest tests/test_prop_integration_fixes.py::test_prop_quant_agent_forwards_teammate_out -x` | ❌ W0 | ⬜ pending |
| 19-01-04 | 01 | 1 | PROP-01 | unit | `python -m pytest tests/test_prop_integration_fixes.py -x -q` | ❌ W0 | ⬜ pending |
| 19-01-05 | 01 | 2 | PROP-01 | integration | `python -m pytest tests/ -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_prop_integration_fixes.py` — 5 stubs covering PROP-01 (INT-2 sport tag + INT-1 teammate_out bridge for NFL and NBA agents)

*All 5 tests require a new file. Existing infrastructure (pytest, pytest-asyncio, conftest.py) covers all other needs.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
