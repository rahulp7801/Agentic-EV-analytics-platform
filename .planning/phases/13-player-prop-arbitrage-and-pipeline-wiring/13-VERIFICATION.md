---
phase: 13-player-prop-arbitrage-and-pipeline-wiring
verified: 2026-03-23T21:00:00Z
status: passed
score: 14/14 must-haves verified
re_verification: false
gaps: []
human_verification: []
---

# Phase 13: Player Prop Arbitrage and Pipeline Wiring — Verification Report

**Phase Goal:** Wire player prop arbitrage into the full LangGraph pipeline so a single ainvoke call produces an EVSignal for both NFL and NBA player prop requests end-to-end.
**Verified:** 2026-03-23T21:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | PropArbitrageAgent returns EVSignal with ev_percentage > 0 when true_probability exceeds implied_probability | VERIFIED | `test_prop06_ev_signal_produced` passes; `prop/arbitrage.py` lines 158-168 compute `compute_ev_percentage` and guard on zero |
| 2  | EVSignal.kelly_fraction is in (0, 0.25] — never flat, never zero | VERIFIED | `test_prop06_kelly_fraction_non_flat` passes; `fractional_kelly` called with `Decimal(str(cfg.max_kelly_fraction))`; EVSignal field constraint `le=Decimal("0.25")` enforces upper bound |
| 3  | EVSignal.trade_plan contains exactly 3 non-empty bullet strings | VERIFIED | `test_prop06_trade_plan_length` passes; `_build_prop_trade_plan` returns `[bullet_1, bullet_2, bullet_3]` — 3 elements, all non-empty strings |
| 4  | PropArbitrageAgent returns ev_signal=None when EV is negative or prop_result is missing | VERIFIED | `test_prop06_no_ev_suppressed` and `test_prop06_missing_prop_result` pass; guards at lines 132-139 and 143-149 and 159-167 of `prop/arbitrage.py` |
| 5  | CorrelationGuard blocks Over pass_yds + Under rec_yds simultaneously on the same signal batch | VERIFIED | `test_prop07_prop_conflict_blocked` passes; `frozenset({"over_pass_yds", "under_rec_yds"})` present in `CONFLICT_PAIRS` |
| 6  | CONFLICT_PAIRS contains all required prop-to-prop and prop-to-game-total pairs | VERIFIED | `test_prop07_conflict_pairs_extended` passes; `correlation_guard.py` has 10 entries: 4 Phase 5 + 6 Phase 13 |
| 7  | GraphState formally declares prop_type and prop_line fields | VERIFIED | `state.py` lines 128-129: `prop_type: str` and `prop_line: Any` declared with docstring entries |
| 8  | create_graph() accepts prop_quant_node, nba_quant_node, prop_arbitrage_node optional parameters | VERIFIED | `test_create_graph_accepts_prop_nodes` passes; `graph.py` lines 136-138 define all 3 params |
| 9  | route_from_master routes nba_prop_analysis -> nba_quant_agent and prop_arbitrage_analysis -> prop_arbitrage_agent | VERIFIED | `test_route_nba_prop_analysis` and `test_route_prop_arbitrage_analysis` pass; `router.py` lines 76-79 |
| 10 | prop_quant_agent and nba_quant_agent chain to prop_arbitrage_agent in a single ainvoke | VERIFIED | `graph.py` lines 278-279: `add_edge("prop_quant_agent", "prop_arbitrage_agent")` and `add_edge("nba_quant_agent", "prop_arbitrage_agent")` |
| 11 | prop_arbitrage_agent chains to correlation_guard -> aggregator -> END when those nodes are provided | VERIFIED | `graph.py` lines 288-293: conditional block wires `prop_arbitrage_agent -> correlation_guard` when guard present, else `-> END` |
| 12 | create_graph_with_sqlite() wires make_prop_arbitrage_agent(sport='nfl') and make_prop_quant_agent and make_nba_quant_agent | VERIFIED | `graph.py` lines 387-397: all three prop nodes wired when pool is not None |
| 13 | End-to-end NFL prop pipeline (pre-injected PropResult) produces non-None EVSignal in one ainvoke | VERIFIED | `test_e2e_nfl_prop_pipeline` (both in test_prop_arbitrage.py and test_prop_pipeline_wiring.py) pass |
| 14 | End-to-end NBA prop pipeline (pre-injected nba_prop_result) produces non-None EVSignal in one ainvoke | VERIFIED | `test_e2e_nba_prop_pipeline` (both in test_prop_arbitrage.py and test_prop_pipeline_wiring.py) pass |

**Score:** 14/14 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sportsbet/prop/arbitrage.py` | make_prop_arbitrage_agent closure factory | VERIFIED | 200 lines; exports `make_prop_arbitrage_agent`; imports `compute_ev_percentage`, `fractional_kelly`, `EVSignal`, `GraphState`; sport param selects state key |
| `src/sportsbet/arbitrage/correlation_guard.py` | Extended CONFLICT_PAIRS with prop-specific pairs | VERIFIED | 55 lines; 10 frozenset pairs; contains `over_pass_yds`; Phase 5 and Phase 13 groupings labelled inline |
| `src/sportsbet/graph/state.py` | GraphState TypedDict with prop_type and prop_line fields | VERIFIED | Lines 128-129 declare `prop_type: str` and `prop_line: Any`; docstring updated at lines 95-104 |
| `tests/test_prop_arbitrage.py` | Full PROP-06 and PROP-07 test suite, min_lines 80 | VERIFIED | 274 lines; 10 tests in 3 classes; all 10 pass |
| `src/sportsbet/graph/graph.py` | create_graph() with 3 new optional node params; create_graph_with_sqlite() wired for props | VERIFIED | Lines 136-138 add params; lines 246-248 register nodes; lines 278-279 chain edges; lines 387-397 wire factory closures |
| `src/sportsbet/graph/router.py` | Extended route_from_master with nba_prop_analysis and prop_arbitrage_analysis routes | VERIFIED | Lines 76-79 add both elif branches; module docstring routing table updated at lines 14-15 |
| `tests/test_prop_pipeline_wiring.py` | Integration tests for full prop pipeline wiring, min_lines 60 | VERIFIED | 274 lines; 7 tests in 3 classes; all 7 pass |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `src/sportsbet/prop/arbitrage.py` | `sportsbet.arbitrage.ev.compute_ev_percentage` | closure import | WIRED | Line 28: `from sportsbet.arbitrage.ev import build_trade_plan, compute_ev_percentage` |
| `src/sportsbet/prop/arbitrage.py` | `sportsbet.arbitrage.kelly.fractional_kelly` | closure import | WIRED | Line 29: `from sportsbet.arbitrage.kelly import fractional_kelly` |
| `src/sportsbet/prop/arbitrage.py` | `sportsbet.graph.state.GraphState` | state.get('prop_result') or state.get('nba_prop_result') | WIRED | Line 31: `from sportsbet.graph.state import GraphState`; lines 120-132 use `_state_key` to select key |
| `tests/test_prop_arbitrage.py` | `src/sportsbet/prop/arbitrage.py` | make_prop_arbitrage_agent import | WIRED | Lines 26-31: try/except import guard; `_IMPORT_OK = True` confirmed by test execution |
| `src/sportsbet/graph/router.py` | `src/sportsbet/graph/graph.py` | conditional edges routing dict keys | WIRED | `graph.py` lines 263-265 contain `"prop_quant_agent"`, `"nba_quant_agent"`, `"prop_arbitrage_agent"` keys matching router return values |
| `src/sportsbet/graph/graph.py` | `src/sportsbet/prop/arbitrage.py` | create_graph_with_sqlite imports make_prop_arbitrage_agent | WIRED | Line 394: `from sportsbet.prop.arbitrage import make_prop_arbitrage_agent` inside pool gate |
| `src/sportsbet/prop/agents.py` | `src/sportsbet/graph/graph.py` | create_graph_with_sqlite imports make_prop_quant_agent | WIRED | Line 392: `from sportsbet.prop.agents import make_prop_quant_agent` |
| `tests/test_prop_pipeline_wiring.py` | `src/sportsbet/graph/graph.py` | create_graph() called with all new prop nodes | WIRED | Lines 170-175, 213-220, 233-240, 255-262: multiple create_graph() calls with all three prop node params |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PROP-06 | 13-01, 13-02 | PropArbitrageAgent reads PropResult.true_probability, computes EV%, generates 3-bullet Trade Plan, outputs fractional Kelly sizing | SATISFIED | `make_prop_arbitrage_agent` in `prop/arbitrage.py`; 10 tests in `test_prop_arbitrage.py`; e2e pipeline tests in `test_prop_pipeline_wiring.py` |
| PROP-07 | 13-01, 13-02 | CorrelationGuard blocks prop-to-prop correlations | SATISFIED | `CONFLICT_PAIRS` extended to 10 entries; `test_prop07_prop_conflict_blocked` and `test_prop07_conflict_pairs_extended` pass |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | — |

No TODO/FIXME/placeholder patterns detected in phase-created files. No stub implementations returning empty values in production paths. All guard clauses properly return `{"ev_signal": None}` (not raise) consistent with LangGraph continuity semantics.

---

### Human Verification Required

None. All observable truths are covered by automated tests:
- EV signal production: unit-tested with known decimal inputs
- Kelly fraction bounds: validated against EVSignal Pydantic constraint
- Trade plan structure: string content verified in tests
- Guard conditions: all 5 guard paths tested
- Correlation guard: blocking and pass-through both tested
- End-to-end pipelines: both NFL and NBA ainvoke paths tested via graph.ainvoke

---

### Verification Results

**Test run: `python -m pytest tests/test_prop_arbitrage.py tests/test_prop_pipeline_wiring.py -v`**

```
17 passed in 0.20s
  - test_prop06_ev_signal_produced            PASSED
  - test_prop06_kelly_fraction_non_flat       PASSED
  - test_prop06_no_ev_suppressed              PASSED
  - test_prop06_trade_plan_length             PASSED
  - test_prop06_missing_prop_result           PASSED
  - test_prop07_prop_conflict_blocked         PASSED
  - test_prop07_conflict_pairs_extended       PASSED
  - test_prop07_no_conflict_passes            PASSED
  - test_e2e_nfl_prop_pipeline (unit)         PASSED
  - test_e2e_nba_prop_pipeline (unit)         PASSED
  - test_route_nba_prop_analysis              PASSED
  - test_route_prop_arbitrage_analysis        PASSED
  - test_create_graph_accepts_prop_nodes      PASSED
  - test_conditional_edges_contain_prop_nodes PASSED
  - test_e2e_nfl_prop_pipeline (integration)  PASSED
  - test_e2e_nba_prop_pipeline (integration)  PASSED
  - test_prop_arbitrage_analysis_direct       PASSED
```

**Full suite regression: `python -m pytest tests/ -x -q`**

```
153 passed, 11 skipped — 0 failures (no regressions across all prior phases)
```

**Commit hashes verified in git log:**
- `817cced` — test(13-01): add failing test stubs for PROP-06 and PROP-07
- `acdf811` — feat(13-01): implement PropArbitrageAgent, extend CorrelationGuard, add GraphState fields
- `748b958` — test(13-02): add failing integration tests for prop pipeline wiring
- `8a9b229` — feat(13-02): extend router and graph with prop pipeline nodes and edges

---

### Summary

Phase 13 fully achieves its goal. The complete prop arbitrage pipeline is wired end-to-end:

- `make_prop_arbitrage_agent` (Plans 01, 13-01) is a substantive closure factory that reads `prop_result` (NFL) or `nba_prop_result` (NBA), computes fractional Kelly-sized EV signals with 3-bullet trade plans, and guards cleanly against all missing-data and negative-EV conditions.
- `CONFLICT_PAIRS` (13-01) is extended from 4 to 10 entries covering prop-to-prop and prop-to-game-total correlations.
- `GraphState` (13-01) formally declares `prop_type: str` and `prop_line: Any`, closing the Pitfall 5 open question from the research phase.
- `route_from_master` (13-02) handles `nba_prop_analysis` and `prop_arbitrage_analysis` request types.
- `create_graph()` (13-02) accepts all three new prop node parameters, registers them, and chains `prop_quant_agent -> prop_arbitrage_agent` and `nba_quant_agent -> prop_arbitrage_agent` with shared downstream `correlation_guard -> aggregator -> END`.
- `create_graph_with_sqlite()` (13-02) wires all three prop nodes in production when a pool is available.
- A single `ainvoke` call with `request_type="prop_analysis"` or `"nba_prop_analysis"` traverses master_router -> prop/nba_quant_agent -> prop_arbitrage_agent -> correlation_guard -> aggregator -> END and produces a non-None `EVSignal`.

All 17 phase-specific tests pass. Zero regressions (153 total passing).

---

_Verified: 2026-03-23T21:00:00Z_
_Verifier: Claude (gsd-verifier)_
