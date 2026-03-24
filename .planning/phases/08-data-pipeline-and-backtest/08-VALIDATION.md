---
phase: 8
slug: data-pipeline-and-backtest
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-22
updated: 2026-03-24
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pyproject.toml` (existing) |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | DATA-03 | integration | `python -m pytest tests/test_context.py::test_context_agent_persists_odds_snapshot -x -q` | ✅ | ✅ green |
| 08-01-02 | 01 | 1 | KINE-01 | unit | `python -m pytest tests/test_kinematic.py::test_matchup_query_returns_avg_time_to_throw -x -q` | ✅ | ✅ green |
| 08-01-03 | 01 | 1 | QUANT-04 | integration | `python -m pytest tests/test_backtest.py::test_backtest_cli_main_prints_output -x -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_context.py` — append `test_context_agent_persists_odds_snapshot` stub asserting `write_odds_snapshot` is called after context agent run (DATA-03)
- [x] `tests/test_backtest.py` — append `test_backtest_cli_main_prints_output` stub asserting `main()` prints hit_rate and roi (QUANT-04)
- [x] `tests/test_kinematic.py` — append `test_matchup_query_returns_avg_time_to_throw` stub (KINE-01)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live odds snapshot actually written to Supabase/Postgres prod DB | DATA-03 | Requires live Odds API key + real DB connection | Run `python -m sportsbet.ingestion.cli fetch-odds`, then `SELECT COUNT(*) FROM odds_snapshots` in DB client |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
