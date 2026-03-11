---
phase: 3
slug: quant-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
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
| 3-01-01 | 01 | 1 | QUANT-01 | unit | `pytest tests/test_quant.py::test_quant_params_validation -x` | ❌ Wave 0 | ⬜ pending |
| 3-01-02 | 01 | 1 | QUANT-01 | unit | `pytest tests/test_quant.py::test_query_builder_parameterized -x` | ❌ Wave 0 | ⬜ pending |
| 3-01-03 | 01 | 1 | QUANT-03 | integration | `pytest tests/test_quant.py::test_run_quant_query_passing -x` | ❌ Wave 0 | ⬜ pending |
| 3-01-04 | 01 | 1 | QUANT-01 | integration | `pytest tests/test_quant.py::test_quant_agent_live -x` | ❌ Wave 0 | ⬜ pending |
| 3-02-01 | 02 | 2 | QUANT-02 | unit | `pytest tests/test_vig.py::test_american_to_raw_prob -x` | ❌ Wave 0 | ⬜ pending |
| 3-02-02 | 02 | 2 | QUANT-02 | unit | `pytest tests/test_vig.py::test_multiplicative_sums_to_one -x` | ❌ Wave 0 | ⬜ pending |
| 3-02-03 | 02 | 2 | QUANT-02 | unit | `pytest tests/test_vig.py::test_power_sums_to_one -x` | ❌ Wave 0 | ⬜ pending |
| 3-03-01 | 03 | 3 | QUANT-04 | unit | `pytest tests/test_backtest.py::test_backtest_engine_fixture -x` | ❌ Wave 0 | ⬜ pending |
| 3-03-02 | 03 | 3 | QUANT-04 | unit | `pytest tests/test_backtest.py::test_backtest_empty_signals -x` | ❌ Wave 0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_quant.py` — stubs for QUANT-01, QUANT-03 (DB tests gated by `SPORTSBET_TEST_DATABASE_URL`)
- [ ] `tests/test_vig.py` — stubs for QUANT-02 (pure unit, no DB required)
- [ ] `tests/test_backtest.py` — stubs for QUANT-04 (pure unit with fixture data)
- [ ] `src/sportsbet/quant/__init__.py` — quant subpackage scaffold
- [ ] `statsmodels>=0.14` added to pyproject.toml dependencies

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| asyncpg pool lifecycle at app startup | QUANT-03 | Pool creation requires live PostgreSQL; test env may not have DB running | Start app with `SPORTSBET_DATABASE_URL` set; verify pool initializes without error in logs |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
