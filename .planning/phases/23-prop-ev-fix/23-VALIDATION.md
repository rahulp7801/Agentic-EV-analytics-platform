---
phase: 23
slug: prop-ev-fix
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `pytest tests/test_prop_arbitrage.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_prop_arbitrage.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 23-01-01 | 01 | 0 | PROP-06 SC-1/SC-2 | unit | `pytest tests/test_prop_arbitrage.py::TestProp06PlayerPropSnapshot -x -q` | ❌ W0 | ⬜ pending |
| 23-01-02 | 01 | 0 | PROP-06 SC-3 | unit | `pytest tests/test_prop_arbitrage.py::TestProp06NoSnapshotGuard -x -q` | ❌ W0 | ⬜ pending |
| 23-01-03 | 01 | 1 | PROP-06 SC-1 | unit | `pytest tests/test_prop_arbitrage.py -x -q` | ✅ exists | ⬜ pending |
| 23-01-04 | 01 | 1 | PROP-06 SC-2 | unit | `pytest tests/test_prop_arbitrage.py -x -q` | ✅ exists | ⬜ pending |
| 23-01-05 | 01 | 1 | PROP-06 SC-3 | unit | `pytest tests/test_prop_arbitrage.py::TestProp06NoSnapshotGuard -x -q` | ❌ W0 | ⬜ pending |
| 23-01-06 | 01 | 2 | PROP-06 SC-4 | unit + e2e | `pytest tests/test_prop_arbitrage.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_prop_arbitrage.py` — add `TestProp06PlayerPropSnapshot` class (SC-1/SC-2: snapshot match, implied_prob source)
- [ ] `tests/test_prop_arbitrage.py` — add `TestProp06NoSnapshotGuard` class (SC-3: empty/None snapshots → `_NO_SIGNAL`)
- [ ] `tests/test_prop_arbitrage.py` — update `_make_nfl_state` and `_make_nba_state` fixtures to include `player_prop_snapshots` list with matching `PlayerPropSnapshotCreate`

*Existing test infrastructure covers pytest framework — no new installs required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| prop_type string format matches Odds API market keys | PROP-06 | Requires live Odds API response or fixture with real market keys to verify normalization | Run a fixture test with actual Odds API prop_type strings and assert match succeeds |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
