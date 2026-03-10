---
phase: 2
slug: agent-infrastructure
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| 02-01-01 | 01 | 1 | INFRA-01 | unit | `pytest tests/test_graph.py::test_graphstate_reducer -q` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | INFRA-02 | unit | `pytest tests/test_graph.py::test_router_dispatch -q` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | INFRA-03 | unit | `pytest tests/test_models.py -q` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 1 | INFRA-03 | unit | `pytest tests/test_models.py::test_ev_signal_validation -q` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 2 | INFRA-04 | unit | `pytest tests/test_graph.py::test_checkpoint_persist -q` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 2 | INFRA-04 | unit | `pytest tests/test_graph.py::test_checkpoint_replay -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_graph.py` — stubs for INFRA-01, INFRA-02, INFRA-04
- [ ] `tests/test_models.py` — stubs for INFRA-03
- [ ] `tests/conftest.py` — add `graph_fixture` with `InMemorySaver` and fresh `thread_id` per test

*Existing `tests/conftest.py` from Phase 1 covers DB fixtures — graph fixtures are additive.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| AsyncSqliteSaver `.sqlite` file written to disk | INFRA-04 | Requires filesystem inspection after `ainvoke` | Run `python -c "import asyncio; from sportsbet.graph import create_graph; asyncio.run(create_graph().ainvoke(...))"` and verify `.checkpoints/sportsbet.sqlite` exists |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
