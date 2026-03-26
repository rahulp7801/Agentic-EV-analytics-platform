---
phase: 22-tech-debt-cleanup
verified: 2026-03-26T19:10:00Z
status: passed
score: 8/8 must-haves verified
re_verification: false
---

# Phase 22: Tech Debt Cleanup Verification Report

**Phase Goal:** Eliminate accumulated tech debt items that are non-blocking but degrade reliability, developer ergonomics, and documentation correctness — including data integrity risks, Python 3.12 compatibility warnings, missing warning logs, and stale documentation text.
**Verified:** 2026-03-26T19:10:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Re-running ingest_pbp_seasons does not raise IntegrityError for rows with non-NULL game_id | VERIFIED | `pg_insert(PlayByPlay).on_conflict_do_nothing(index_elements=["game_id","play_id"])` present at pbp.py lines 98-100; test passes |
| 2  | pytest tests/test_graph.py tests/test_quant.py -W error::DeprecationWarning passes with zero warnings | VERIFIED | 22 passed, 2 skipped — no DeprecationWarning raised; line 200 uses `datetime.now(timezone.utc)` |
| 3  | The string "TODO placeholder" does not appear anywhere in src/sportsbet/prop/agents.py | VERIFIED | Python pathlib check confirms absence; module docstring is PROP-04 accurate description |
| 4  | log.warning is called when kinematic_result is None and prop_type is in RECEIVING_PROPS | VERIFIED | agents.py lines 185-190 contain the conditional `log.warning("prop_quant_agent_kinematic_missing", ...)`; test passes |
| 5  | python -m sportsbet.quant.backtest_replay --help prints usage without error | VERIFIED | CLI exits 0 and prints full argparse help when PYTHONPATH includes src and site-packages |
| 6  | CLV-only mode works without --outcomes-file: BacktestReport with clv_mean populated | VERIFIED | test_clv_only_mode passes; build_signals sets actual_outcome=False; report.clv_mean not None |
| 7  | Full ROI mode works when --outcomes-file is provided with actual outcome data | VERIFIED | test_full_roi_mode passes; hit_rate populated; all 3 test_backtest_pipeline.py tests pass |
| 8  | REQUIREMENTS.md DATA-02 line contains 'nflreadpy' and does not contain 'nfl_data_py' | VERIFIED | Line 11 reads "via nflreadpy using a year-by-year loading loop" — nfl_data_py absent |

**Score:** 8/8 truths verified

---

## Required Artifacts

### Plan 01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sportsbet/ingestion/pbp.py` | Idempotent PBP write using pg_insert().on_conflict_do_nothing() | VERIFIED | `on_conflict_do_nothing` present at lines 98-100; `to_sql` removed; chunked loop implemented |
| `tests/test_pbp_idempotency.py` | Test asserting duplicate insert is silent (no IntegrityError) | VERIFIED | `test_pbp_on_conflict_do_nothing` function exists and passes |
| `tests/test_graph.py` | datetime.now(timezone.utc) replaces datetime.utcnow() | VERIFIED | Line 200 uses `datetime.now(timezone.utc)`; no `utcnow` remaining |
| `src/sportsbet/prop/agents.py` | Accurate module docstring + WARNING log on None kinematic for receiving props | VERIFIED | Docstring replaced with PROP-04 contract text; `log.warning("prop_quant_agent_kinematic_missing", ...)` at lines 186-190 |
| `tests/test_prop_quant_warning.py` | caplog test asserting warning is emitted | VERIFIED | `test_kinematic_missing_warning` uses structlog.testing.capture_logs(); passes |

### Plan 02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sportsbet/quant/backtest_replay.py` | CLI script: odds_snapshots -> BacktestSignal -> BacktestReport | VERIFIED | `main`, `load_snapshots`, `build_signals` all present and substantive; 267 lines |
| `tests/test_backtest_pipeline.py` | Unit tests for snapshot->signal mapping and CLV-only mode | VERIFIED | `test_clv_only_mode`, `test_full_roi_mode`, `test_empty_snapshots` all present and passing |
| `.planning/REQUIREMENTS.md` | DATA-02 text updated to nflreadpy | VERIFIED | Line 11 confirmed; "nfl_data_py" absent from all DATA-02 lines |

---

## Key Link Verification

### Plan 01 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/sportsbet/ingestion/pbp.py` | `sportsbet.db.models.PlayByPlay` | `pg_insert(PlayByPlay).on_conflict_do_nothing(index_elements=['game_id','play_id'])` | WIRED | Lines 98-100 match expected pattern exactly |
| `src/sportsbet/prop/agents.py` | structlog warning | `log.warning('prop_quant_agent_kinematic_missing', ...)` | WIRED | Lines 185-190; conditional fires when kinematic_result is None AND prop_type in RECEIVING_PROPS |

### Plan 02 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/sportsbet/quant/backtest_replay.py` | `sportsbet.quant.backtest.BacktestEngine` | `BacktestEngine().run(signals)` | WIRED | Line 209; called inside `_async_main` after build_signals |
| `src/sportsbet/quant/backtest_replay.py` | `backtest_replay._american_to_implied_prob` | inline conversion in build_signals | WIRED | Lines 101-102; `_american_to_implied_prob(price)` and `_american_to_payout(price)` called with Decimal returns |
| `src/sportsbet/quant/backtest_replay.py` | odds_snapshots table | `snapped_at < game_start_time WHERE clause` | WIRED | Line 155: `"o.snapped_at < (g.game_date::timestamptz + INTERVAL '18 hours')"` hardcoded in where_clauses |

---

## Requirements Coverage

No requirement IDs declared in either plan (requirements: [] in both frontmatters). Phase goal was implementation-level tech debt — not tied to functional REQUIREMENTS.md rows. DATA-02 documentation fix confirmed in place.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/sportsbet/ingestion/nba.py` | 109 | `df.to_sql(...)` (pandas UserWarning for non-SQLAlchemy DBAPI2) | Warning (pre-existing) | Not introduced by Phase 22; 4 warnings in full suite run — all from pre-existing nba.py; does not affect phase 22 deliverables |

No Phase 22 files contain: TODO/FIXME/PLACEHOLDER strings, `return null`/`return {}` stubs, empty handler patterns, or `console.log`-only implementations.

Note: The 4 UserWarnings in the full suite (`nba.py:109`) are pre-existing tech debt outside Phase 22 scope. Phase 22 introduced zero new warnings.

---

## Human Verification Required

None. All success criteria are programmatically verifiable and confirmed passing.

---

## Gaps Summary

No gaps. All 8 observable truths verified, all 8 artifacts confirmed substantive and wired, all 5 key links confirmed wired. Full test suite passes (206 passed, 11 skipped, 2 xfailed). Phase goal achieved.

### Commit Verification

All commits referenced in summaries confirmed present in git history:
- `f58531f` — test(22-01): RED TDD stubs
- `a79404d` — fix(22-01): PBP idempotency + datetime fix
- `33bd1e3` — fix(22-01): stale docstring + PROP-04 warning
- `508c614` — test(22-02): failing tests for backtest_replay
- `2b74291` — feat(22-02): backtest_replay CLI + DATA-02 fix

---

_Verified: 2026-03-26T19:10:00Z_
_Verifier: Claude (gsd-verifier)_
