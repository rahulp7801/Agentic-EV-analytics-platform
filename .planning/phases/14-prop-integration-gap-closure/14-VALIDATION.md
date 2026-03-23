---
phase: 14
slug: prop-integration-gap-closure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-23
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
| 14-01-01 | 01 | 0 | PROP-01 | unit stub | `pytest tests/test_prop_integration_gap_closure.py -x` | ❌ W0 | ⬜ pending |
| 14-01-02 | 01 | 0 | INFRA-01 | unit stub | `pytest tests/test_prop_integration_gap_closure.py -x` | ❌ W0 | ⬜ pending |
| 14-01-03 | 01 | 1 | PROP-01 | unit (mock patch) | `pytest tests/test_prop_integration_gap_closure.py::test_context_agent_calls_write_player_prop_snapshot -x` | ❌ W0 | ⬜ pending |
| 14-01-04 | 01 | 1 | PROP-06/NBA-02 | integration | `pytest tests/test_prop_pipeline_wiring.py::TestE2EPropPipelineWiring::test_e2e_nba_prop_pipeline -x` | ✅ | ⬜ pending |
| 14-01-05 | 01 | 1 | INFRA-01 | unit | `pytest tests/test_prop_integration_gap_closure.py::test_graphstate_declares_prop_filters -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_prop_integration_gap_closure.py` — stubs covering:
  - PROP-01 wiring: `make_context_agent` calls `write_player_prop_snapshot` at least once after `fetch_player_props` returns data (mock at module level)
  - PROP-06: `sport=None` auto-detection resolves NBA state key correctly
  - INFRA-01: `GraphState` TypedDict contains `prop_filters` field
- [ ] Update `tests/test_prop_pipeline_wiring.py` `_make_base_state()` to include `prop_filters: {}` — required once `prop_filters` declared in `GraphState`

*Existing infrastructure (pytest asyncio_mode=auto, pythonpath=['src','site-packages']) covers all phase requirements. No new framework install needed.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
