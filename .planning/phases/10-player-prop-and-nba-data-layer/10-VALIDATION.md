---
phase: 10
slug: player-prop-and-nba-data-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2 + pytest-asyncio 0.23 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_prop_models.py tests/test_prop_odds.py tests/test_nba_ingestion.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_prop_models.py tests/test_prop_odds.py tests/test_nba_ingestion.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | PROP-01 | unit (mocked httpx) | `pytest tests/test_prop_odds.py::test_fetch_nfl_player_props -x` | ❌ W0 | ⬜ pending |
| 10-01-02 | 01 | 1 | PROP-01 | unit (mocked engine) | `pytest tests/test_prop_odds.py::test_write_player_prop_snapshot -x` | ❌ W0 | ⬜ pending |
| 10-01-03 | 01 | 1 | PROP-01 | integration (DB) | `pytest tests/test_migrations.py -x -k "prop"` | ❌ W0 | ⬜ pending |
| 10-01-04 | 01 | 1 | PROP-02 | unit | `pytest tests/test_prop_models.py::test_prop_params_invalid_prop_type -x` | ❌ W0 | ⬜ pending |
| 10-01-05 | 01 | 1 | PROP-02 | unit | `pytest tests/test_prop_models.py::test_prop_params_invalid_season -x` | ❌ W0 | ⬜ pending |
| 10-01-06 | 01 | 1 | PROP-02 | unit | `pytest tests/test_prop_models.py::test_prop_result_all_nullable -x` | ❌ W0 | ⬜ pending |
| 10-02-01 | 02 | 2 | NBA-01 | unit (mocked nba_api) | `pytest tests/test_nba_ingestion.py::test_nba_season_format -x` | ❌ W0 | ⬜ pending |
| 10-02-02 | 02 | 2 | NBA-01 | unit (mocked) | `pytest tests/test_nba_ingestion.py::test_nba_column_whitelist -x` | ❌ W0 | ⬜ pending |
| 10-02-03 | 02 | 2 | NBA-01 | integration (DB) | `pytest tests/test_migrations.py -x -k "nba"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_prop_models.py` — stubs for PROP-02 PropParams/PropResult validation
- [ ] `tests/test_prop_odds.py` — stubs for PROP-01 fetch + write; uses `unittest.mock.patch` for httpx client
- [ ] `tests/test_nba_ingestion.py` — stubs for NBA-01; mocks `nba_api.stats.endpoints.LeagueDashPlayerStats`
- [ ] `pip install nba_api` + add `"nba_api>=1.11"` to `pyproject.toml`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `OddsAPIPoller` handles empty NBA event list (offseason) gracefully | PROP-01 | Requires offseason API state to reproduce | Run `fetch_player_props("nba")` against live API during offseason; confirm no exception raised |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
