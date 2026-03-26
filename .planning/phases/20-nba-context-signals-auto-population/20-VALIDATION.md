---
phase: 20
slug: nba-context-signals-auto-population
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-25
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio (asyncio_mode = "auto") |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/test_nba_context_producer.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_nba_context_producer.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 20-01-01 | 01 | 1 | PROP-05, NBA-02 | unit | `python -m pytest tests/test_nba_context_producer.py -x -q` | ❌ W0 | ⬜ pending |
| 20-01-02 | 01 | 1 | PROP-05, NBA-02 | unit + integration | `python -m pytest tests/test_nba_context_producer.py -x -q` | ❌ W0 | ⬜ pending |
| 20-01-03 | 01 | 1 | PROP-05, NBA-02 | integration | `python -m pytest tests/ -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_nba_context_producer.py` — stubs for all 6 test cases (new file)
- [ ] `src/sportsbet/prop/nba_context_producer.py` — producer module stub (new file)

*All test stubs must be created before Wave 1 implementation tasks begin.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Graph routing shows `nba_context_producer` in node list | PROP-05 | LangGraph graph introspection | Run graph and print `graph.nodes` — confirm `nba_context_producer` appears before `nba_quant_agent` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
