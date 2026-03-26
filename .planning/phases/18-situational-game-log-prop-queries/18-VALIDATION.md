---
phase: 18
slug: situational-game-log-prop-queries
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-24
updated: 2026-03-26
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pyproject.toml` ([tool.pytest.ini_options]) |
| **Quick run command** | `pytest tests/ -x -q --tb=short` |
| **Full suite command** | `pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `pytest tests/ -v --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | SC-1: nba_player_gamelogs table | unit | `pytest tests/test_nba_gamelogs_schema.py -x -q` | ✅ | ✅ green |
| 18-01-02 | 01 | 1 | SC-1: ingest pipeline populates records | integration | `pytest tests/test_nba_gamelogs_ingest.py -x -q` | ✅ | ✅ green |
| 18-01-03 | 01 | 1 | SC-2: injury-join for game_id (NBA + NFL) | unit | `pytest tests/test_gamelog_injury_join.py -x -q` | ✅ | ✅ green (2 xfail — SC-2 covered by test_prop_query_builder_situational.py GREEN) |
| 18-02-01 | 02 | 2 | SC-3: PropParams optional filter fields | unit | `pytest tests/test_prop_params_situational.py -x -q` | ✅ | ✅ green |
| 18-02-02 | 02 | 2 | SC-3: GraphState / ContextAgent injection | unit | `pytest tests/test_context_agent_params.py -x -q` | ✅ | ✅ green |
| 18-03-01 | 03 | 3 | SC-4: QueryBuilder dynamic WHERE clauses | unit | `pytest tests/test_prop_query_builder_situational.py -x -q` | ✅ | ✅ green |
| 18-03-02 | 03 | 3 | SC-5: Wilson CI widens for small samples | unit | `pytest tests/test_executor_small_sample.py -x -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_nba_gamelogs_schema.py` — stubs for SC-1 (nba_player_gamelogs ORM model + migration)
- [x] `tests/test_nba_gamelogs_ingest.py` — stubs for SC-1 (PlayerGameLogs ingest pipeline)
- [x] `tests/test_gamelog_injury_join.py` — stubs for SC-2 (injury-join for NBA and NFL game_id) — XFAIL acceptable; SC-2 production behavior covered by GREEN test in test_prop_query_builder_situational.py
- [x] `tests/test_prop_params_situational.py` — stubs for SC-3 (PropParams optional fields: last_n_games, teammate_out, opponent_team, home_away)
- [x] `tests/test_context_agent_params.py` — stubs for SC-3 (GraphState injection of situational params)
- [x] `tests/test_prop_query_builder_situational.py` — stubs for SC-4 (dynamic WHERE clause construction)
- [x] `tests/test_executor_small_sample.py` — stubs for SC-5 (Wilson CI graceful widening, nobs<30)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| NBA PlayerGameLogs API returns data for current season | SC-1 | Requires live NBA API call | Run `python -c "from nba_api.stats.endpoints import PlayerGameLogs; r = PlayerGameLogs(season_nullable='2024-25'); print(len(r.get_data_frames()[0]))"` — expect >0 rows |
| `teammate_out` date-window approximation accuracy | SC-2 | Approximation; no automated truth | Manually verify a known game where a starter was out and check returned injury_reports rows fall within ±2 day window |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Self-approved 2026-03-26 — all 27 Phase 18 tests GREEN or XFAIL (25 passed, 2 xfailed); test_gamelog_injury_join.py xfail stubs acceptable per Phase 17 precedent; full suite 201 passed, 11 skipped-DB, 2 xfailed.
