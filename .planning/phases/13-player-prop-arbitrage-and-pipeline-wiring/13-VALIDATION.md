---
phase: 13
slug: player-prop-arbitrage-and-pipeline-wiring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-23
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pytest.ini / pyproject.toml |
| **Quick run command** | `python -m pytest tests/test_prop_arbitrage.py tests/test_correlation_guard.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_prop_arbitrage.py tests/test_correlation_guard.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | PROP-06 | unit | `python -m pytest tests/test_prop_arbitrage.py -x -q` | ❌ W0 | ⬜ pending |
| 13-01-02 | 01 | 1 | PROP-07 | unit | `python -m pytest tests/test_correlation_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 13-02-01 | 02 | 2 | PROP-06 | integration | `python -m pytest tests/test_prop_pipeline_wiring.py -x -q` | ❌ W0 | ⬜ pending |
| 13-02-02 | 02 | 2 | PROP-07 | integration | `python -m pytest tests/test_prop_pipeline_wiring.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_prop_arbitrage.py` — failing stubs for PropArbitrageAgent EV%, Trade Plan, Kelly sizing
- [ ] `tests/test_correlation_guard.py` — failing stubs for extended CONFLICT_PAIRS (prop-to-prop)
- [ ] `tests/test_prop_pipeline_wiring.py` — failing stubs for end-to-end pipeline integration

*Existing pytest infrastructure in place — only new test files required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end pipeline against real DB | PROP-06 | Requires live PostgreSQL with nfl_player_stats and nba_player_stats populated | Run `python -m pytest tests/test_prop_pipeline_wiring.py -x -q -m integration` with real DB env vars set |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
