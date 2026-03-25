---
phase: 17
slug: nyquist-compliance
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-24
updated: 2026-03-24
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2 + pytest-asyncio 0.23 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/ -x -q --tb=short` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 1 | Phase 3 wave_0 | smoke | `pytest tests/test_quant.py tests/test_vig.py tests/test_backtest.py -x -q` | ✅ | ✅ green |
| 17-01-02 | 01 | 1 | Phase 4 wave_0 | smoke | `pytest tests/test_context.py -x -q` | ✅ | ✅ green |
| 17-01-03 | 01 | 1 | Phase 5 wave_0 | smoke | `pytest tests/test_arbitrage.py -x -q` | ✅ | ✅ green |
| 17-01-04 | 01 | 1 | Phase 6 wave_0 | smoke | `pytest tests/test_kinematic.py -x -q` | ✅ | ✅ green |
| 17-01-05 | 01 | 1 | Phase 7 wave_0 | smoke | `pytest tests/test_graph.py -k "Phase7Wiring" -x -q` | ✅ | ✅ green |
| 17-01-06 | 01 | 1 | Phase 8 wave_0 | smoke | `pytest tests/test_backtest.py::test_backtest_cli_main_prints_output tests/test_kinematic.py::test_matchup_query_returns_avg_time_to_throw -x -q` | ✅ | ✅ green |
| 17-01-07 | 01 | 1 | Phase 9 wave_0 | smoke | `pytest tests/test_context.py::test_context_agent_rejects_stale_odds -x -q` | ✅ | ✅ green |
| 17-02-01 | 02 | 2 | Phase 10 wave_0 | smoke | `pytest tests/test_prop_models.py tests/test_prop_odds.py tests/test_nba_ingestion.py -x -q` | ✅ | ✅ green |
| 17-02-02 | 02 | 2 | Phase 11 wave_0 | smoke | `pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x -q` | ✅ | ✅ green |
| 17-02-03 | 02 | 2 | Phase 12 wave_0 | smoke | `pytest tests/test_nba_prop_query_builder.py tests/test_nba_prop_executor.py -x -q` | ✅ | ✅ green |
| 17-02-04 | 02 | 2 | Phase 13 wave_0 | smoke | `pytest tests/test_prop_arbitrage.py tests/test_prop_pipeline_wiring.py -x -q` | ✅ | ✅ green |
| 17-02-05 | 02 | 2 | Phase 14 wave_0 | smoke | `pytest tests/test_prop_integration_gap_closure.py -x -q` | ✅ | ✅ green |
| 17-02-06 | 02 | 2 | Phase 15 wave_0 | smoke | `pytest tests/test_context_and_vig_completion.py -x -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. Phase 17 is a documentation repair phase — all test files already exist and pass. No new test files are needed.

*Wave 0 = full suite already green: `pytest tests/ -x -q` → 163 passed, 11 skipped (DB-gated), 0 failed*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Self-approved 2026-03-24 — all 13 phase VALIDATION.md files updated to nyquist_compliant: true. Full suite: 163 passed, 11 skipped-DB, 0 failed.
