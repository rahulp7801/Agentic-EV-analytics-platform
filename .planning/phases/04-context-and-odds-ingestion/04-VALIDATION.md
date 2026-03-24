---
phase: 4
slug: context-and-odds-ingestion
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-13
updated: 2026-03-24
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2 + pytest-asyncio 0.23 |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `pytest tests/test_context.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_context.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 0 | CTXT-01 | unit | `pytest tests/test_context.py::test_odds_poller_writes_snapshot -x` | ✅ | ✅ green |
| 4-01-02 | 01 | 0 | CTXT-01 | unit | `pytest tests/test_context.py::test_budget_exhausted_raises -x` | ✅ | ✅ green |
| 4-01-03 | 01 | 0 | CTXT-02 | unit | `pytest tests/test_context.py::test_staleness_guard_rejects_stale -x` | ✅ | ✅ green |
| 4-01-04 | 01 | 0 | CTXT-02 | unit | `pytest tests/test_context.py::test_staleness_guard_passes_fresh -x` | ✅ | ✅ green |
| 4-02-01 | 02 | 0 | CTXT-03 | unit | `pytest tests/test_context.py::test_espn_injury_parsing -x` | ✅ | ✅ green |
| 4-02-02 | 02 | 0 | CTXT-03 | integration | `pytest tests/test_context.py::test_scraper_writes_injury_report -x` | ✅ | ✅ green |
| 4-03-01 | 03 | 0 | CTXT-04 | unit | `pytest tests/test_context.py::test_context_agent_updates_graphstate -x` | ✅ | ✅ green |
| 4-03-02 | 03 | 0 | CTXT-04 | integration | `pytest tests/test_context.py::test_downstream_reads_state -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_context.py` — stubs for CTXT-01 through CTXT-04 (8 test functions)
- [x] `alembic/versions/0002_add_injury_reports.py` — hand-written migration (no autogenerate per Phase 1 decision)
- [x] `src/sportsbet/db/models.py` — `InjuryReport` ORM model with composite indexes
- [x] `src/sportsbet/graph/models.py` — `ContextSignals` Pydantic model (strict=True)
- [x] `src/sportsbet/graph/state.py` — `context_signals: ContextSignals | None` field added to `GraphState`
- [x] Framework: `pip install httpx tenacity playwright beautifulsoup4 lxml && playwright install chromium`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Odds API call returns real NFL odds and writes timestamped snapshot | CTXT-01 | Requires live API key; mocked in unit tests; credit cost per call | Set `SPORTSBET_TEST_ODDS_API_KEY`, run `pytest tests/test_context.py -m live -x`, verify row in `odds_snapshots` |
| Budget manager daily cap persists across process restarts | CTXT-01 | Process restart not automatable in standard pytest | Restart process mid-day, confirm `x-requests-remaining` loaded from DB/file, not reset to None |
| ESPN Core API injury response field schema | CTXT-03 | Undocumented API; field names need live validation | Run `pytest tests/test_context.py::test_espn_injury_parsing -x` with `--live` flag; inspect raw JSON |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
