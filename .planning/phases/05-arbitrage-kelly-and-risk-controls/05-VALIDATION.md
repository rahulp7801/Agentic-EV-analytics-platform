---
phase: 5
slug: arbitrage-kelly-and-risk-controls
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-14
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `python -m pytest tests/test_arbitrage.py -x -q` |
| **Full suite command** | `python -m pytest -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_arbitrage.py -x -q`
- **After every plan wave:** Run `python -m pytest -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 5-01-01 | 01 | 1 | ARBT-01,02 | unit stub | `python -m pytest tests/test_arbitrage.py -x -q` | ❌ W0 | ⬜ pending |
| 5-01-02 | 01 | 1 | ARBT-01 | unit | `python -m pytest tests/test_arbitrage.py::test_arbt01 -x -q` | ❌ W0 | ⬜ pending |
| 5-01-03 | 01 | 1 | ARBT-02 | unit | `python -m pytest tests/test_arbitrage.py::test_arbt02 -x -q` | ❌ W0 | ⬜ pending |
| 5-02-01 | 02 | 1 | ARBT-03 | unit | `python -m pytest tests/test_arbitrage.py::test_arbt03 -x -q` | ❌ W0 | ⬜ pending |
| 5-02-02 | 02 | 1 | ARBT-03 | unit | `python -m pytest tests/test_arbitrage.py::test_arbt03 -x -q` | ❌ W0 | ⬜ pending |
| 5-03-01 | 03 | 1 | ARBT-04 | unit | `python -m pytest tests/test_arbitrage.py::test_arbt04 -x -q` | ❌ W0 | ⬜ pending |
| 5-03-02 | 03 | 1 | ARBT-04 | unit | `python -m pytest tests/test_arbitrage.py::test_arbt04 -x -q` | ❌ W0 | ⬜ pending |
| 5-04-01 | 04 | 2 | ARBT-01..04 | integration | `python -m pytest tests/test_arbitrage.py::test_e2e_pipeline -x -q` | ❌ W0 | ⬜ pending |
| 5-04-02 | 04 | 2 | ARBT-01..04 | integration | `python -m pytest tests/test_arbitrage.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_arbitrage.py` — stubs for ARBT-01, ARBT-02, ARBT-03, ARBT-04 (8 total)
- [ ] Existing `tests/conftest.py` — reuse Phase 3/4 fixtures (no new conftest needed)

*Existing pytest infrastructure covers all phase requirements — no new framework install.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Trade Plan thesis is coherent English prose (3 bullets) | ARBT-01 | LLM output quality is subjective | Run pipeline, read trade_plan field, verify 3 bullets are readable and logical |
| Kelly fraction output feels conservative under uncertainty | ARBT-02 | Numerical reasonableness requires domain judgment | Verify kelly_fraction ≤ 0.25 AND is not trivially 0 for edge > 0 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
