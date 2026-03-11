---
phase: 2
slug: agent-infrastructure
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-10
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (asyncio_mode="auto") |
| **Config file** | `pyproject.toml` — already configured from Phase 1 |
| **Quick run command** | `pytest tests/test_graph.py -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~3 seconds (no DB, no network — pure unit tests) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_graph.py -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | INFRA-03 | unit | `pytest tests/test_models.py -q` | created in TDD RED step | ⬜ pending |
| 02-01-02 | 01 | 1 | INFRA-03 | unit | `pytest tests/test_models.py::test_ev_signal_validation -q` | created in TDD RED step | ⬜ pending |
| 02-02-01 | 02 | 2 | INFRA-01 | unit | `pytest tests/test_graph.py::test_graphstate_reducer -q` | created in TDD RED step | ⬜ pending |
| 02-02-02 | 02 | 2 | INFRA-02 | unit | `pytest tests/test_graph.py::test_router_dispatch_quant -q` | created in TDD RED step | ⬜ pending |
| 02-03-01 | 03 | 3 | INFRA-04 | unit | `pytest tests/test_graph.py::test_checkpoint_persist -q` | created in TDD RED step | ⬜ pending |
| 02-03-02 | 03 | 3 | INFRA-04 | unit | `pytest tests/test_graph.py::test_checkpoint_replay -q` | created in TDD RED step | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 — Test Scaffold

Test files are created as part of the TDD RED phase at the start of each plan's first task. There are no separate Wave 0 tasks required:

- **Plan 01 (Wave 1, TDD):** `tests/test_models.py` is written in the RED step of Task 1 before any production code exists. 10 failing tests expected on first run.
- **Plan 02 (Wave 2, TDD):** `tests/test_graph.py` is written in the RED step of Task 1 before `state.py` is implemented. 9 failing tests expected on first run.
- **Plan 03 (Wave 3, TDD Task 2):** Checkpoint tests are added to `tests/test_graph.py` in the RED step of Task 2. 4 failing tests expected on first run.
- **`tests/conftest.py`:** `graph_fixture` (MemorySaver + fresh thread_id) added in Plan 03 Task 2.

All test creation is embedded in the RED phase of each plan's TDD task — no separate scaffolding step needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SqliteSaver `.sqlite` file written to disk | INFRA-04 | Requires filesystem inspection after `ainvoke` | Run `python -c "import asyncio; from sportsbet.graph import create_graph_with_sqlite; ..."` and verify `.checkpoints/sportsbet.sqlite` exists |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify — test files created in TDD RED steps (embedded in plans)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covered by TDD RED steps in each plan — no outstanding MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved
