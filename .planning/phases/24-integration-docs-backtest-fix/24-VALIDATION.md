---
phase: 24
slug: integration-docs-backtest-fix
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pytest.ini / pyproject.toml |
| **Quick run command** | `pytest tests/test_backtest_pipeline.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_backtest_pipeline.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 24-01-01 | 01 | 1 | ARBT-01 | manual/grep | `grep -n "two-invocation" src/sportsbet/graph.py` | ✅ | ⬜ pending |
| 24-01-02 | 01 | 1 | CTXT-04/PROP-04 | manual/grep | `grep -n "Invocation ordering" src/sportsbet/prop/agents.py src/sportsbet/prop/nba_agents.py` | ✅ | ⬜ pending |
| 24-01-03 | 01 | 1 | QUANT-04 | unit | `pytest tests/test_backtest_pipeline.py -x -q -k "null_game_id"` | ❌ W0 | ⬜ pending |
| 24-01-04 | 01 | 1 | QUANT-04 | unit | `pytest tests/test_backtest_pipeline.py -x -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_backtest_pipeline.py` — add NULL game_id fixture stub for QUANT-04

*Existing infrastructure covers all other phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| graph.py comment describes two-invocation pattern | ARBT-01 | Documentation check, not runtime behavior | grep for "two-invocation" or "quant_analysis before arbitrage_analysis" in graph.py |
| prop agent docstrings describe invocation ordering | CTXT-04/PROP-04 | Documentation check | grep for "Invocation ordering" in prop/agents.py and prop/nba_agents.py |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
