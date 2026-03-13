---
phase: 03-quant-engine
verified: 2026-03-13T20:00:00Z
status: passed
score: 17/17 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Run test_run_quant_query_passing and test_quant_agent_live against a real PostgreSQL instance populated with play_by_play data"
    expected: "QuantResult with non-None sample_size, data_source='postgresql', and data_source != 'fixture' from graph ainvoke"
    why_human: "Requires SPORTSBET_TEST_DATABASE_URL and seeded play_by_play table; cannot be verified without live DB"
---

# Phase 3: Quant Engine Verification Report

**Phase Goal:** The system can produce a statistically grounded true probability estimate from PostgreSQL data, validated through a two-stage SQL gate with no raw SQL ever leaving the LLM
**Verified:** 2026-03-13T20:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Malformed QuantParams (invalid season, injected SQL fragment as stat_type) raises ValidationError and never reaches QueryBuilder.build() | VERIFIED | test_quant_params_validation and test_quant_params_sql_injection both pass; QuantParams uses Literal["passing","rushing","receiving"] and Field(ge=1999, le=2030) |
| 2  | QueryBuilder.build() with valid QuantParams returns (sql_str, args_tuple) where no user-supplied data appears in sql_str — all values are in args_tuple as $1/$2 positional params | VERIFIED | test_query_builder_parameterized passes; code confirms sql templates are static strings, args list holds [posteam, season, ...filter_values]; confirmed "KC" never in sql, "$1" always present |
| 3  | run_quant_query() against a mock pool returning 50 rows returns a QuantResult with true_probability, sample_size, confidence_interval, and data_source all non-None | VERIFIED | test_run_quant_query_mock_adequate_sample passes; CI bounds are Decimal instances; data_source="postgresql" |
| 4  | make_quant_agent(pool) is the async closure factory — the stub fixture value is gone from the real code path | VERIFIED | agents.py: make_quant_agent returns async callable wrapping run_quant_query; sync stub quant_agent preserved for backward-compat but data_source="fixture" is only in stub, not in closure factory |
| 5  | MIN_SAMPLE_SIZE gate: if query returns fewer than 30 rows, QuantResult.true_probability is None and data_source is 'insufficient_sample' | VERIFIED | test_insufficient_sample passes; executor.py line 80 confirms gate: if total < MIN_SAMPLE_SIZE: return QuantResult(data_source="insufficient_sample") |
| 6  | american_to_raw_prob(-110) returns Decimal within 6 decimal places of Decimal('0.523809') | VERIFIED | test_american_to_raw_prob_negative passes; vig.py uses Decimal(str(american_odds)) — no float construction |
| 7  | remove_vig_multiplicative([-110,-110] raw probs) returns values summing to exactly Decimal('1') | VERIFIED | test_multiplicative_sums_to_one passes with == (not approx); residual correction on last element guarantees exact equality |
| 8  | remove_vig_power([-110,-110] raw probs) returns values summing within Decimal('1e-6') of Decimal('1') | VERIFIED | test_power_sums_to_one passes; binary search uses corrected range [1.0, 20.0] |
| 9  | Overround <= 1 guard raises ValueError before any division | VERIFIED | test_multiplicative_overround_guard passes; vig.py line 72: if overround <= Decimal("1"): raise ValueError |
| 10 | All return values from vig functions are Decimal, never float | VERIFIED | test_power_returns_decimals and test_american_to_raw_prob_returns_decimal pass; float() confined to binary search loop only |
| 11 | BacktestEngine.run(5 signals, 3 wins) returns BacktestReport with hit_rate==0.6, roi==0.1454, sample_size==5 | VERIFIED | test_backtest_engine_fixture and test_backtest_roi_calculation pass; vectorized pandas ops confirmed in backtest.py |
| 12 | BacktestEngine.run([]) returns BacktestReport with sample_size=0 and roi/hit_rate/clv_mean all None | VERIFIED | test_backtest_empty_signals passes; empty-list guard at backtest.py line 126 |
| 13 | CLV calculation uses closing_implied_prob - signal_implied_prob; positive CLV when signal beats close | VERIFIED | test_backtest_clv_positive_when_signal_beats_close passes; clv_mean == 0.05 (0.60 - 0.55) |
| 14 | BacktestEngine is a standalone offline module — never imported from graph.py or any agent node | VERIFIED | grep confirms no import of backtest in src/sportsbet/graph/; docstring in backtest.py documents isolation invariant |
| 15 | BacktestEngine.run() with null true_probability signal skips that signal, emits warning, sample_size reflects only valid signals | VERIFIED | test_backtest_skips_null_probability_signal passes; structlog.warning("skipping_null_probability_signal") emitted per skipped signal |
| 16 | No raw f-string SQL construction anywhere in quant subpackage | VERIFIED | grep for f"WHERE / f'WHERE / f"SELECT / f'SELECT / f"AND / f'AND returns no results in src/sportsbet/quant/ |
| 17 | All existing Phase 2 tests still pass — no regressions | VERIFIED | Full suite: 51 passed, 9 skipped, 0 failures |

**Score:** 17/17 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sportsbet/quant/__init__.py` | Quant subpackage marker | VERIFIED | File exists |
| `src/sportsbet/quant/query_builder.py` | QueryBuilder class with build() classmethod | VERIFIED | 118 lines; exports QueryBuilder; ALLOWED_FILTER_KEYS frozenset; three static SQL templates; no f-string user data |
| `src/sportsbet/quant/executor.py` | run_quant_query async function, Wilson CI computation, MIN_SAMPLE_SIZE | VERIFIED | 118 lines; MIN_SAMPLE_SIZE=30; proportion_confint("wilson"); Decimal(str(round(x,6))) CI wrapping |
| `src/sportsbet/quant/vig.py` | american_to_raw_prob, remove_vig_multiplicative, remove_vig_power | VERIFIED | 130 lines; all three functions exported; binary search range [1.0, 20.0] corrected from plan's (0,1] |
| `src/sportsbet/quant/backtest.py` | BacktestSignal, BacktestReport, BacktestEngine | VERIFIED | 194 lines; all three exported; standalone offline module; closing_line_note field present |
| `src/sportsbet/graph/agents.py` | make_quant_agent(pool) closure factory; get_or_create_pool; sync stub preserved | VERIFIED | make_quant_agent at line 56; get_or_create_pool at line 39; stub quant_agent at line 115 |
| `src/sportsbet/graph/graph.py` | create_graph(quant_node=None) param; create_graph_with_sqlite(pool=None) | VERIFIED | quant_node param at line 35; create_graph_with_sqlite pool param at line 97; backward-compat confirmed |
| `tests/test_quant.py` | 8 test functions (6 unit, 2 DB-gated) | VERIFIED | 8 functions present; 6 unit pass; 2 skipped without SPORTSBET_TEST_DATABASE_URL |
| `tests/test_vig.py` | 9 unit tests covering QUANT-02 | VERIFIED | 9 functions; all pass |
| `tests/test_backtest.py` | 6 unit tests covering QUANT-04 | VERIFIED | 6 functions; all pass |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/sportsbet/graph/agents.py` | `src/sportsbet/quant/executor.py` | make_quant_agent closure calls run_quant_query(pool, params) | WIRED | agents.py line 72: `from sportsbet.quant.executor import run_quant_query`; called at line 87 |
| `src/sportsbet/quant/executor.py` | `src/sportsbet/quant/query_builder.py` | executor calls QueryBuilder.build(params) before asyncpg execute | WIRED | executor.py line 29: `from sportsbet.quant.query_builder import QueryBuilder`; called at line 65 |
| `src/sportsbet/quant/query_builder.py` | `src/sportsbet/graph/models.py` | build() accepts QuantParams; FilterKey guards filter dict injection | WIRED | query_builder.py line 14: `from sportsbet.graph.models import QuantParams`; build() signature: `def build(cls, params: QuantParams)` |
| `tests/test_vig.py` | `src/sportsbet/quant/vig.py` | direct import — no DB, no asyncpg, no graph dependency | WIRED | test_vig.py line 10: `from sportsbet.quant.vig import american_to_raw_prob, remove_vig_multiplicative, remove_vig_power` |
| `src/sportsbet/quant/backtest.py` | `src/sportsbet/graph/models.py` | BacktestSignal references QuantResult | WIRED | backtest.py line 32: `from sportsbet.graph.models import QuantResult`; BacktestSignal.quant_result: QuantResult |
| `tests/test_backtest.py` | `src/sportsbet/quant/backtest.py` | direct import — no DB, no asyncpg, no graph dependency | WIRED | test_backtest.py line 25: `from sportsbet.quant.backtest import BacktestEngine, BacktestReport, BacktestSignal` |
| `src/sportsbet/graph/graph.py` | `src/sportsbet/graph/agents.py` | create_graph_with_sqlite calls make_quant_agent(pool) when pool provided | WIRED | graph.py line 137: `from sportsbet.graph.agents import make_quant_agent`; line 138: `quant_node = make_quant_agent(pool)` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| QUANT-01 | 03-01-PLAN.md | Two-stage SQL validation gate — LLM produces QuantParams, query builder constructs parameterized SQL, LLM never produces raw SQL | SATISFIED | QuantParams Literal stat_type + ALLOWED_FILTER_KEYS frozenset + asyncpg $N params; 4 unit tests pass; no f-string SQL confirmed by grep |
| QUANT-02 | 03-02-PLAN.md | Convert raw sportsbook odds to implied probabilities with configurable vig removal (multiplicative or Pinnacle sharp) | SATISFIED | vig.py exports three functions; 9 unit tests pass; all return Decimal; overround guard raises ValueError |
| QUANT-03 | 03-01-PLAN.md | Execute dynamic historical win-rate SQL queries parameterized by game context | SATISFIED | run_quant_query executes parameterized queries with Wilson CI; MIN_SAMPLE_SIZE gate; mock-pool tests pass; live DB tests skipped (not blocked) |
| QUANT-04 | 03-03-PLAN.md | Simulate historical signal performance via backtesting module replaying past QuantResult signals against closing lines | SATISFIED | BacktestEngine.run() produces ROI/hit_rate/CLV; 6 unit tests pass; standalone isolation confirmed |

All four Phase 3 requirements verified as SATISFIED. No orphaned requirements — REQUIREMENTS.md lists QUANT-01 through QUANT-04 mapped to Phase 3, all accounted for by plans 03-01, 03-02, and 03-03.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/test_quant.py` | 136 | `asyncio.get_event_loop().run_until_complete()` deprecated in Python 3.10+ | Info | DeprecationWarning in test output; does not affect correctness; test passes; should use `asyncio.run()` in a future cleanup pass |

No blocker anti-patterns found. No TODO/FIXME/placeholder comments in any quant source file. No empty return stubs. No f-string SQL. The single DeprecationWarning is a test hygiene issue, not a goal blocker.

---

### Human Verification Required

#### 1. Live PostgreSQL Integration

**Test:** Set `SPORTSBET_TEST_DATABASE_URL` to a PostgreSQL instance with the `play_by_play` table populated with at least 30 rows for a given team/season combination, then run `pytest tests/test_quant.py -k "test_run_quant_query_passing or test_quant_agent_live" -v`
**Expected:** `test_run_quant_query_passing` returns a QuantResult with non-None sample_size; `test_quant_agent_live` graph ainvoke returns quant_result.data_source != "fixture"
**Why human:** Requires live PostgreSQL instance with seeded play_by_play data; cannot be verified programmatically in a dry-run environment

---

### Gaps Summary

No gaps. All 17 observable truths verified. All 10 required artifacts exist, are substantive, and are correctly wired. All 7 key links confirmed. All 4 requirements (QUANT-01 through QUANT-04) satisfied. No blocker anti-patterns.

The one item flagged for human verification is the live DB integration path — both integration tests are correctly gated by `pytest.mark.skipif` and will execute correctly once `SPORTSBET_TEST_DATABASE_URL` is configured. The skip behavior itself is correct and the test logic is sound.

Notable engineering decisions confirmed correct by inspection:
- Power devig binary search range corrected to [1.0, 20.0] from plan's (0.0, 1.0] — summary documents this deviation as a Rule 1 auto-fix; the implementation is mathematically correct
- Multiplicative devig exact sum-to-one via residual correction on last element — eliminates accumulated Decimal division remainder; test confirms `sum(fair) == Decimal("1")` with `==` (not `approx`)
- `Decimal(str(round(x, 6)))` wrapping for Wilson CI bounds — prevents QuantResult strict=True Pydantic rejection of raw float values from statsmodels

---

_Verified: 2026-03-13T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
