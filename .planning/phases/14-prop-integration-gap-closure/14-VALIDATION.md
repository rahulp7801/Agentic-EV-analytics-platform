---
phase: 14
slug: prop-integration-gap-closure
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-23
updated: 2026-03-24
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest with `asyncio_mode = "auto"` |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_prop_odds.py tests/test_prop_pipeline_wiring.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_prop_odds.py tests/test_prop_pipeline_wiring.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 0 | PROP-01 | unit stub | `pytest tests/test_prop_integration_gap_closure.py -x` | ✅ | ✅ green |
| 14-01-02 | 01 | 0 | INFRA-01 | unit stub | `pytest tests/test_prop_integration_gap_closure.py -x` | ✅ | ✅ green |
| 14-01-03 | 01 | 1 | PROP-01 | unit (mock patch) | `pytest tests/test_prop_integration_gap_closure.py::test_context_agent_calls_write_player_prop_snapshot -x` | ✅ | ✅ green |
| 14-01-04 | 01 | 1 | PROP-06/NBA-02 | integration | `pytest tests/test_prop_pipeline_wiring.py::TestE2EPropPipelineWiring::test_e2e_nba_prop_pipeline -x` | ✅ | ✅ green |
| 14-01-05 | 01 | 1 | INFRA-01 | unit | `pytest tests/test_prop_integration_gap_closure.py::test_graphstate_declares_prop_filters -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_prop_integration_gap_closure.py` — stubs covering:
  - PROP-01 wiring: `make_context_agent` calls `write_player_prop_snapshot` at least once after `fetch_player_props` returns data (mock at module level)
  - PROP-06: `sport=None` auto-detection resolves NBA state key correctly
  - INFRA-01: `GraphState` TypedDict contains `prop_filters` field
- [x] Update `tests/test_prop_pipeline_wiring.py` `_make_base_state()` to include `prop_filters: {}` — required once `prop_filters` declared in `GraphState`

*Existing infrastructure (pytest asyncio_mode=auto, pythonpath=['src','site-packages']) covers all phase requirements. No new framework install needed.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
