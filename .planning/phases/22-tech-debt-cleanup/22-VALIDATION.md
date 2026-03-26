---
phase: 22
slug: tech-debt-cleanup
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -W error::DeprecationWarning` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -W error::DeprecationWarning`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 22-01-01 | 01 | 1 | SC-1 PBP idempotency | integration | `pytest tests/ -k "pbp" -q` | ❌ W0 | ⬜ pending |
| 22-01-02 | 01 | 1 | SC-2 Python 3.12 deprecations | unit | `pytest tests/test_graph.py tests/test_quant.py -W error::DeprecationWarning -q` | ✅ | ⬜ pending |
| 22-01-03 | 01 | 1 | SC-3 stale docstring | static | `grep -c "TODO placeholder" src/sportsbet/prop/agents.py` | ✅ | ⬜ pending |
| 22-01-04 | 01 | 1 | SC-4 PROP-04 None warning | unit | `pytest tests/ -k "prop_quant" -q` | ❌ W0 | ⬜ pending |
| 22-02-01 | 02 | 1 | SC-6 QUANT-04 pipeline | integration | `pytest tests/ -k "backtest" -q` | ❌ W0 | ⬜ pending |
| 22-02-02 | 02 | 1 | SC-5 DATA-02 text fix | static | `grep "nflreadpy" .planning/REQUIREMENTS.md` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_pbp_idempotency.py` — stub verifying ON CONFLICT DO NOTHING prevents IntegrityError on duplicate PBP rows (SC-1)
- [ ] `tests/test_prop_quant_warning.py` — stub verifying WARNING log emitted when `kinematic_result` is None on receiving prop (SC-4)
- [ ] `tests/test_backtest_pipeline.py` — stub verifying odds_snapshots → BacktestSignal CLI entry point exists and is callable (SC-6)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| QUANT-04 CLV output is sensible | SC-6 | Requires live DB with odds_snapshots rows | Run `python -m sportsbet.quant.backtest_pipeline --help` and verify output format |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
