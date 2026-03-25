---
phase: 13
slug: player-prop-arbitrage-and-pipeline-wiring
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-23
updated: 2026-03-24
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pytest.ini / pyproject.toml |
| **Quick run command** | `python -m pytest tests/test_prop_arbitrage.py tests/test_prop_pipeline_wiring.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_prop_arbitrage.py tests/test_prop_pipeline_wiring.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | PROP-06 | unit | `python -m pytest tests/test_prop_arbitrage.py -x -q` | ✅ | ✅ green |
| 13-01-02 | 01 | 1 | PROP-07 | unit | `python -m pytest tests/test_prop_arbitrage.py::TestProp07CorrelationGuard -x -q` | ✅ | ✅ green |
| 13-02-01 | 02 | 2 | PROP-06 | integration | `python -m pytest tests/test_prop_pipeline_wiring.py -x -q` | ✅ | ✅ green |
| 13-02-02 | 02 | 2 | PROP-07 | integration | `python -m pytest tests/test_prop_pipeline_wiring.py -x -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_prop_arbitrage.py` — failing stubs for PropArbitrageAgent EV%, Trade Plan, Kelly sizing
- [x] `tests/test_prop_arbitrage.py` (TestProp07CorrelationGuard class) — PROP-07 extended CorrelationGuard conflict matrix; CorrelationGuard tests consolidated here during Phase 13 execution
- [x] `tests/test_prop_pipeline_wiring.py` — failing stubs for end-to-end pipeline integration

*Existing pytest infrastructure in place — only new test files required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end pipeline against real DB | PROP-06 | Requires live PostgreSQL with nfl_player_stats and nba_player_stats populated | Run `python -m pytest tests/test_prop_pipeline_wiring.py -x -q -m integration` with real DB env vars set |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
