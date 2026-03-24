---
phase: 3
slug: quant-engine
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-10
updated: 2026-03-24
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2 + pytest-asyncio 0.23 |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| **Quick run command** | `pytest tests/test_quant.py tests/test_vig.py tests/test_backtest.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~15 seconds (unit tests only; DB integration tests skipped if no SPORTSBET_TEST_DATABASE_URL) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_quant.py tests/test_vig.py tests/test_backtest.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | QUANT-01 | unit | `pytest tests/test_quant.py::test_quant_params_validation -x` | ✅ | ✅ green |
| 3-01-02 | 01 | 1 | QUANT-01 | unit | `pytest tests/test_quant.py::test_query_builder_parameterized -x` | ✅ | ✅ green |
| 3-01-03 | 01 | 1 | QUANT-03 | integration | `pytest tests/test_quant.py::test_run_quant_query_passing -x` | ✅ | ⬜ pending (skipif DB) |
| 3-01-04 | 01 | 1 | QUANT-01 | integration | `pytest tests/test_quant.py::test_quant_agent_live -x` | ✅ | ⬜ pending (skipif DB) |
| 3-02-01 | 02 | 2 | QUANT-02 | unit | `pytest tests/test_vig.py::test_american_to_raw_prob -x` | ✅ | ✅ green |
| 3-02-02 | 02 | 2 | QUANT-02 | unit | `pytest tests/test_vig.py::test_multiplicative_sums_to_one -x` | ✅ | ✅ green |
| 3-02-03 | 02 | 2 | QUANT-02 | unit | `pytest tests/test_vig.py::test_power_sums_to_one -x` | ✅ | ✅ green |
| 3-03-01 | 03 | 3 | QUANT-04 | unit | `pytest tests/test_backtest.py::test_backtest_engine_fixture -x` | ✅ | ✅ green |
| 3-03-02 | 03 | 3 | QUANT-04 | unit | `pytest tests/test_backtest.py::test_backtest_empty_signals -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_quant.py` — stubs for QUANT-01, QUANT-03 (DB tests gated by `SPORTSBET_TEST_DATABASE_URL`)
- [x] `tests/test_vig.py` — stubs for QUANT-02 (pure unit, no DB required)
- [x] `tests/test_backtest.py` — stubs for QUANT-04 (pure unit with fixture data)
- [x] `src/sportsbet/quant/__init__.py` — quant subpackage scaffold
- [x] `statsmodels>=0.14` added to pyproject.toml dependencies

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| asyncpg pool lifecycle at app startup | QUANT-03 | Pool creation requires live PostgreSQL; test env may not have DB running | Start app with `SPORTSBET_DATABASE_URL` set; verify pool initializes without error in logs |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
