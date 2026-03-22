---
phase: 8
slug: data-pipeline-and-backtest
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
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
| 08-01-01 | 01 | 1 | DATA-03 | integration | `python -m pytest tests/test_odds_snapshot_persistence.py -x -q` | ❌ W0 | ⬜ pending |
| 08-01-02 | 01 | 1 | KINE-01 | unit | `python -m pytest tests/test_kinematic_agent.py -x -q -k avg_time_to_throw` | ✅ | ⬜ pending |
| 08-01-03 | 01 | 1 | QUANT-04 | integration | `python -m pytest tests/test_backtest_cli.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_odds_snapshot_persistence.py` — stub asserting `write_odds_snapshot` is called after context agent run and a row appears in `odds_snapshots` (DATA-03)
- [ ] `tests/test_backtest_cli.py` — stub asserting `python -m sportsbet.quant.backtest` exits 0 and stdout contains ROI and hit-rate (QUANT-04)

*Existing `tests/test_kinematic_agent.py` covers the KINE-01 avg_time_to_throw fixture — no new file needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live odds snapshot actually written to Supabase/Postgres prod DB | DATA-03 | Requires live Odds API key + real DB connection | Run `python -m sportsbet.ingestion.cli fetch-odds`, then `SELECT COUNT(*) FROM odds_snapshots` in DB client |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
