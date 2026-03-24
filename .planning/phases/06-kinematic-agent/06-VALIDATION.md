---
phase: 6
slug: kinematic-agent
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-15
updated: 2026-03-24
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2 with pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (asyncio_mode = "auto") |
| **Quick run command** | `python -m pytest tests/test_kinematic.py -x` |
| **Full suite command** | `python -m pytest tests/ -x` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_kinematic.py -x`
- **After every plan wave:** Run `python -m pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 6-01-01 | 01 | 0 | KINE-01 | unit | `pytest tests/test_kinematic.py::test_matchup_query_returns_ngs_fields -x` | ✅ | ✅ green |
| 6-01-02 | 01 | 0 | KINE-02 | unit | `pytest tests/test_kinematic.py::test_mismatch_flag_set_on_high_separation -x` | ✅ | ✅ green |
| 6-01-03 | 01 | 0 | KINE-02 | unit | `pytest tests/test_kinematic.py::test_kinematic_analysis_has_no_quant_fields -x` | ✅ | ✅ green |
| 6-01-04 | 01 | 0 | KINE-03 | unit | `pytest tests/test_kinematic.py::test_unavailable_season_returns_none_fields -x` | ✅ | ✅ green |
| 6-01-05 | 01 | 0 | KINE-03 | unit | `pytest tests/test_kinematic.py::test_kinematic_params_rejects_pre_ngs_season -x` | ✅ | ✅ green |
| 6-01-06 | 01 | 1 | KINE-01+02+03 | integration | `pytest tests/test_kinematic.py::test_make_kinematic_agent_end_to_end -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_kinematic.py` — stubs for KINE-01 through KINE-03 (6 test stubs)
- [x] `src/sportsbet/kinematic/__init__.py` — package marker
- [x] `src/sportsbet/kinematic/models.py` — KinematicParams, KinematicAnalysis Pydantic models
- [x] `src/sportsbet/kinematic/availability.py` — check_ngs_availability() async function
- [x] `src/sportsbet/kinematic/matchup.py` — run_matchup_query() async function

*Existing pytest-asyncio infrastructure covers all async test requirements — no new framework installs needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `signal_description` is human-readable and references correct WR/CB names | KINE-02 | String content quality check | Invoke `make_kinematic_agent(pool)` with a known WR-CB matchup; verify `signal_description` text is coherent and non-hallucinated |
| `press_man_rate` is `None` for all queried players (not 0) | KINE-01 | Confirms nullable forward-compat column behavior | Check `KinematicAnalysis.press_man_rate` is `None`, not `Decimal("0")`, in any result |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
