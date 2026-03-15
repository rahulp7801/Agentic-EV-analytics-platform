---
phase: 05-arbitrage-kelly-and-risk-controls
verified: 2026-03-14T22:00:00Z
status: passed
score: 13/13 must-haves verified
re_verification: false
gaps: []
human_verification: []
---

# Phase 5: Arbitrage, Kelly, and Risk Controls — Verification Report

**Phase Goal:** Build the Arbitrage Agent with fractional Kelly Criterion bet sizing, CorrelationGuard for conflicting market exposure prevention, and Aggregator for daily drawdown enforcement. Wire all three into the LangGraph graph as a full arbitrage pipeline.
**Verified:** 2026-03-14T22:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Arbitrage Agent compares QuantResult.true_probability against implied_probability and produces positive ev_percentage only when true_probability > implied_probability | VERIFIED | `compute_ev_percentage` returns `max(Decimal("0"), true_prob - implied_prob)`. `make_arbitrage_agent` guards on `ev_pct == Decimal("0")` and returns `{"ev_signal": None}`. Tests 4, 5, 7 confirm. |
| 2 | Kelly fraction is computed as f* = (b*p - q)/b multiplied by Settings.max_kelly_fraction, hard-capped at 0.25, never output as a flat dollar amount | VERIFIED | `kelly.py` line 60-62 implements `f_star = (b*p-q)/b`, applies `fraction`, returns `max(_ZERO, min(_CAP, result))` with `_CAP = Decimal("0.25")`. All arithmetic pure Decimal. Tests 1, 2, 3, 8 confirm. |
| 3 | EVSignal.trade_plan contains exactly 3 bullet strings describing edge, Kelly sizing rationale, and injury/weather context | VERIFIED | `build_trade_plan` in `ev.py` explicitly returns `[bullet_1, bullet_2, bullet_3]` — exactly 3 items. `EVSignal.trade_plan max_length=3` enforced by Pydantic. Test 6 and e2e test_e2e_pipeline line 604 confirm. |
| 4 | When true_probability <= implied_probability the arbitrage agent returns no ev_signal (negative EV is never flagged) | VERIFIED | `compute_ev_percentage` floors at zero; `make_arbitrage_agent` returns `{"ev_signal": None}` when `ev_pct == Decimal("0")`. Test 5 (compute returns 0) and test_e2e_pipeline_negative_ev confirm. |
| 5 | CorrelationGuard blocks both signals when a conflicting market pair is detected | VERIFIED | `CorrelationGuard.check()` uses frozenset set-intersection; if `pair.issubset(market_types_present)`, both market types added to `blocked` set. Tests 9 and e2e test_e2e_correlation_guard_blocks confirm. |
| 6 | CorrelationGuard passes through non-conflicting signals without modification | VERIFIED | Signals not in any `blocked` set pass through unchanged. Test 10 (single moneyline signal) and test 12 (partial conflict: moneyline passes, over/under blocked) confirm. |
| 7 | Aggregator enforces daily drawdown gate — after cumulative kelly_fraction * bankroll_usd exceeds configured daily_drawdown_limit, it emits no further signals | VERIFIED | `Aggregator.record_signal()` checks `cumulative + exposure >= limit`; sets `_gate_triggered = True` and returns False. Gate stays closed permanently. Tests 14, 15, 16, and e2e test_e2e_pipeline_drawdown_gate confirm. |
| 8 | Aggregator resets its exposure counter on process restart with a fresh instance | VERIFIED | `Aggregator.__init__` sets `self._cumulative = Decimal("0")` and `self._gate_triggered = False`. Each new instance starts fresh. No persistence in v1 by design. |
| 9 | An end-to-end pipeline run returns an ArbitrageSignal with raw EV percentage, 3-bullet Trade Plan, and fractional Kelly fraction | VERIFIED | `test_e2e_pipeline` runs the full `arbitrage_agent -> correlation_guard -> aggregator -> END` chain, asserts `ev_percentage > 0`, `len(trade_plan) == 3`, `kelly_fraction in (0, 0.25]`, `cleared_signals` has 1 item. |
| 10 | CorrelationGuard node runs before the Aggregator in the pipeline — conflicting signals never reach the drawdown gate | VERIFIED | `graph.py` lines 202-204: `builder.add_edge("arbitrage_agent", "correlation_guard")`, `builder.add_edge("correlation_guard", "aggregator")`, `builder.add_edge("aggregator", END)`. Topology enforced by sequential edges. |
| 11 | All Phase 2 tests still pass — create_graph() without arbitrage_node uses the sync stub arbitrage_agent unchanged | VERIFIED | Full suite: 79 passed, 9 skipped, 0 failed. `arbitrage_agent` sync stub preserved in `agents.py` lines 392-415. `create_graph()` falls back to stub when `arbitrage_node=None`. |
| 12 | Full Context -> Quant -> Arbitrage -> CorrelationGuard -> Aggregator chain can be driven end-to-end by integration test using mock state | VERIFIED | 4 integration tests in `tests/test_arbitrage.py` (lines 567-757) use pre-populated state pattern, `MemorySaver`, and real node factories. All 4 pass. |
| 13 | GraphState extended with pending_signals and cleared_signals fields | VERIFIED | `state.py` lines 91-92 add `pending_signals: list[Any]` and `cleared_signals: list[Any]`. `make_arbitrage_agent` writes `pending_signals=[signal]`. Aggregator node reads `pending_signals` and writes `cleared_signals`. |

**Score: 13/13 truths verified**

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sportsbet/arbitrage/__init__.py` | Package marker | VERIFIED | 8 lines, documented exports for kelly, ev submodules |
| `src/sportsbet/arbitrage/kelly.py` | `fractional_kelly(p, b, fraction) -> Decimal` | VERIFIED | 63 lines. Correct formula `f_star = (b*p - q)/b * fraction`, cap at 0.25, floor at 0. Pure Decimal arithmetic. |
| `src/sportsbet/arbitrage/ev.py` | `compute_ev_percentage`, `build_trade_plan` | VERIFIED | 107 lines. EV = `max(0, true_prob - implied_prob)`. Trade plan returns exactly 3 strings. |
| `src/sportsbet/arbitrage/correlation_guard.py` | `CorrelationGuard` class with `CONFLICT_PAIRS` | VERIFIED | 47 lines. `CONFLICT_PAIRS` frozenset with 4 pairs including `frozenset({"over_passing_yards", "under_total_points"})`. Stateless `check()` method. |
| `src/sportsbet/arbitrage/aggregator.py` | `Aggregator` class with daily drawdown gate | VERIFIED | 80 lines. `record_signal() -> bool`, `cumulative_exposure_usd` property, `gate_triggered` property. Gate-closes-on-limit semantics. |
| `src/sportsbet/graph/agents.py` | `make_arbitrage_agent()` closure | VERIFIED | Lines 268-362. Async closure with 5 guards, EV/Kelly computation, EVSignal construction, `pending_signals=[signal]` in return dict. Sync stub preserved at lines 392-415. |
| `src/sportsbet/graph/graph.py` | `create_graph()` extended; `make_correlation_guard_node()`, `make_aggregator_node()` | VERIFIED | `create_graph()` now accepts `arbitrage_node`, `correlation_guard_node`, `aggregator_node`. Conditional topology: when both guard and aggregator provided, sequential edges wired. Both factory functions present lines 52-106. |
| `src/sportsbet/graph/router.py` | `route_from_master` handles `arbitrage_analysis` | VERIFIED | Line 64: `elif request_type in ("odds_check", "arbitrage_analysis"): return "arbitrage_agent"`. Conditional edges map at graph.py line 188 includes `"arbitrage_analysis": "arbitrage_agent"`. |
| `src/sportsbet/graph/state.py` | `pending_signals` and `cleared_signals` on GraphState | VERIFIED | Lines 91-92 add both fields. Docstring describes their semantics. |
| `tests/test_arbitrage.py` | 20 tests covering ARBT-01 through ARBT-04 plus 4 integration tests | VERIFIED | 20 tests total (8 unit Plan 01, 8 unit Plan 02, 4 integration Plan 03). All 20 pass. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `arbitrage/ev.py` | `graph/models.py EVSignal` | `EVSignal(ev_percentage=..., kelly_fraction=..., trade_plan=...)` constructor | WIRED | `agents.py` line 344: `signal = EVSignal(ev_percentage=ev_pct, ...)`. Pydantic enforces all constraints at construction time. |
| `graph/agents.py make_arbitrage_agent` | `graph/state.py GraphState` | `state["quant_result"]` and `state["context_signals"].odds_snapshot` | WIRED | Lines 301-302: `quant_result = state.get("quant_result")`, `context_signals = state.get("context_signals")`. 5 guard clauses validate before math. |
| `graph/graph.py` | `arbitrage/correlation_guard.py CorrelationGuard` | `make_correlation_guard_node()` wraps `CorrelationGuard().check()` as a LangGraph node | WIRED | Lines 60-68: `guard = CorrelationGuard()`, `correlation_guard_node` calls `guard.check(raw)`. |
| `graph/graph.py` | `arbitrage/aggregator.py Aggregator` | `make_aggregator_node()` wraps `Aggregator.record_signal()` as a LangGraph node | WIRED | Lines 92-106: `agg = Aggregator(...)`, `aggregator_node` calls `agg.record_signal(sig)` per candidate. |
| `graph/state.py GraphState` | `arbitrage/correlation_guard.py` | `GraphState.pending_signals` holds signals before guard check | WIRED | `pending_signals: list[Any]` field in `state.py` line 91. Written by `make_arbitrage_agent` return dict, read by `correlation_guard_node`. |
| `arbitrage/aggregator.py` | `config.py Settings` | `Settings.bankroll_usd` and `Settings.max_kelly_fraction` for exposure math | WIRED | `Aggregator.__init__` takes `bankroll_usd: float` directly. `make_arbitrage_agent` reads `cfg.max_kelly_fraction` via `Decimal(str(cfg.max_kelly_fraction))` (line 339). |

---

## Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ARBT-01 | 05-01, 05-03 | Arbitrage Agent flags +EV discrepancies by comparing QuantResult true probability against sportsbook implied probability, outputting raw EV percentage and a 3-bullet Trade Plan thesis | SATISFIED | `compute_ev_percentage`, `build_trade_plan`, `make_arbitrage_agent` all implemented and tested. `test_arbt01_ev_signal_produced` and `test_e2e_pipeline` confirm. |
| ARBT-02 | 05-01, 05-03 | System calculates fractional Kelly Criterion bet sizing based on edge and bankroll parameters — no flat bet sizes are ever output | SATISFIED | `fractional_kelly(p, b, fraction)` implemented in `kelly.py`. `make_arbitrage_agent` uses `Decimal(str(cfg.max_kelly_fraction))` as fraction, never outputs dollar amounts. `test_arbt02_kelly_fraction_non_flat` confirms. |
| ARBT-03 | 05-02, 05-03 | CorrelationGuard node enforces hardcoded stops on conflicting market exposures before any signal is output | SATISFIED | `CorrelationGuard` with `CONFLICT_PAIRS` (4 pairs) in `correlation_guard.py`. Wired before Aggregator in graph topology. `test_arbt03_*` tests and `test_e2e_correlation_guard_blocks` confirm. |
| ARBT-04 | 05-02, 05-03 | Aggregator node enforces a daily drawdown gate — if cumulative recommended exposure exceeds the configured limit, no further signals are produced that day | SATISFIED | `Aggregator.record_signal() -> bool` with permanent gate-closes-on-limit semantics. Wired as final node before END. `test_arbt04_*` tests and `test_e2e_pipeline_drawdown_gate` confirm. |

**All 4 Phase 5 requirements satisfied. No orphaned requirements.**

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| No anti-patterns found | — | — | — | — |

Scan results:
- No `TODO`, `FIXME`, `XXX`, `HACK`, or `PLACEHOLDER` comments in `src/sportsbet/arbitrage/`
- No `return null`, `return {}`, `return []`, or `=> {}` empty implementations
- No float-to-Decimal field assignments in arbitrage subpackage (float used only for display f-string formatting in `build_trade_plan`, explicitly documented)
- Sync stub `arbitrage_agent` retained intentionally for backward-compat — not a placeholder for Phase 5 functionality

---

## Human Verification Required

None. All Phase 5 success criteria are verifiable programmatically via the test suite:

- EV percentage arithmetic: verified by unit tests with known Decimal values
- Kelly fraction bounds: verified by test assertions on `kelly_fraction in (0, 0.25]`
- Trade plan length: verified by `len(trade_plan) == 3` assertion
- CorrelationGuard blocking: verified by `cleared_signals == []` assertion
- Drawdown gate triggering: verified by `ev_signal is None` assertion after tiny-limit Aggregator

---

## Test Suite Summary

```
tests/test_arbitrage.py — 20 passed (8 Plan 01 + 8 Plan 02 + 4 Plan 03 integration)
Full suite — 79 passed, 9 skipped, 0 failed
```

Skipped tests are pre-existing skips for Phase 6 (Kinematic Agent) modules not yet implemented — unrelated to Phase 5.

---

## Commit Verification

All 6 Phase 5 commits present in repository (confirmed via `git log --oneline | grep`):

| Commit | Description |
|--------|-------------|
| `37f5fd1` | feat(05-01): arbitrage subpackage — kelly.py, ev.py, test scaffold |
| `ee0b7f7` | feat(05-01): make_arbitrage_agent closure — real Kelly/EV arbitrage agent |
| `2288a91` | test(05-02): add failing tests for CorrelationGuard and Aggregator (TDD RED) |
| `f97d34d` | feat(05-02): implement CorrelationGuard with CONFLICT_PAIRS conflict detection |
| `572879a` | feat(05-02): implement Aggregator daily drawdown gate |
| `9d41dc7` | feat(05-03): extend GraphState and wire CorrelationGuard + Aggregator as LangGraph nodes |
| `7a5d39c` | test(05-03): add e2e integration tests for full arbitrage pipeline |

---

## Gaps Summary

No gaps. All must-haves verified, all requirements satisfied, all tests pass, no anti-patterns found. Phase 5 goal is fully achieved.

---

_Verified: 2026-03-14T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
