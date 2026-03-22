---
phase: 07-production-runtime-wiring
plan: 01
subsystem: graph
tags: [langgraph, vig, devig, graphstate, kinematic, arbitrage, risk-controls]

# Dependency graph
requires:
  - phase: 05-arbitrage-kelly-and-risk-controls
    provides: make_arbitrage_agent, make_correlation_guard_node, make_aggregator_node
  - phase: 06-kinematic-agent
    provides: make_kinematic_agent, KinematicAnalysis
  - phase: 03-quant-engine
    provides: vig.py (american_to_raw_prob, remove_vig_multiplicative)
provides:
  - receiver_gsis_id field in GraphState TypedDict (INT-02 closure)
  - _extract_odds_snapshot using devigged implied_probability via remove_vig_multiplicative (INT-04 closure)
  - create_graph_with_sqlite() wiring all 6 nodes including Phase 5/6 nodes (INT-01 closure)
  - TestPhase7Wiring test class with 3 assertions confirming all structural gaps closed
affects: [08-frontend, production-entrypoint, ev-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy import pattern inside _extract_odds_snapshot for vig.py — mirrors existing Phase 4 pattern"
    - "Pool-conditional node wiring in create_graph_with_sqlite — arbitrage_node and kinematic_node only built when pool provided"
    - "Decimal.quantize(10dp) normalization for sub-ulp residual elimination after remove_vig_multiplicative"

key-files:
  created:
    - tests (TestPhase7Wiring class added to tests/test_graph.py)
  modified:
    - src/sportsbet/graph/state.py
    - src/sportsbet/graph/agents.py
    - src/sportsbet/graph/graph.py
    - tests/test_graph.py
    - tests/test_arbitrage.py

key-decisions:
  - "Decimal.quantize(Decimal('0.0000000001'), ROUND_HALF_EVEN) applied to fair_probs[0] before storing as implied_probability — remove_vig_multiplicative residual correction fixes last element only, leaving first element with sub-ulp error; 10dp rounding eliminates this without losing Kelly precision"
  - "arbitrage_node and kinematic_node pool-gated in create_graph_with_sqlite — both require DB access; correlation_guard and aggregator always wired (stateless/stateful-in-process respectively)"
  - "receiver_gsis_id: str added as last field in GraphState after kinematic_result — consistent with Phase 4 and 6 field addition patterns"

patterns-established:
  - "Pattern: Vig-aware probability pipeline — all implied_probability values stored in AgentOddsSnapshot are now devigged via remove_vig_multiplicative; callers receive fair probabilities not sportsbook-vig-inclusive ones"

requirements-completed: [QUANT-02, ARBT-01, ARBT-03, ARBT-04, KINE-01, KINE-02]

# Metrics
duration: 5min
completed: 2026-03-22
---

# Phase 7 Plan 01: Production Runtime Wiring Summary

**Three surgical edits closing INT-01/02/04 audit gaps: receiver_gsis_id in GraphState, devigged EV probability via remove_vig_multiplicative, and all 6 nodes wired into create_graph_with_sqlite()**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-22T20:17:50Z
- **Completed:** 2026-03-22T20:22:15Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Added `receiver_gsis_id: str` field to GraphState TypedDict, closing INT-02 (kinematic agent could silently query with empty string)
- Replaced inline vig-inclusive American odds math in `_extract_odds_snapshot` with `remove_vig_multiplicative` from vig.py, closing INT-04 (EV math was systematically understating edge)
- Extended `create_graph_with_sqlite()` to wire `make_arbitrage_agent()`, `make_correlation_guard_node()`, `make_aggregator_node()`, and `make_kinematic_agent(pool)`, closing INT-01 (production factory only built Phase 2 stubs)
- All 92 tests pass (9 skipped for DB tests without test DB URL)

## Task Commits

1. **Task 1: Write Wave 0 test stubs and update existing test helpers** - `9440f13` (test)
2. **Task 2: Add receiver_gsis_id to GraphState and wire vig removal** - `2e06303` (feat)
3. **Task 3: Extend create_graph_with_sqlite() with all Phase 5/6 nodes** - `473ea21` (feat)

## Files Created/Modified

- `tests/test_graph.py` - Added TestPhase7Wiring class (3 test methods); updated make_minimal_state() and make_checkpoint_state() with receiver_gsis_id
- `tests/test_arbitrage.py` - Updated _base_state() with receiver_gsis_id
- `src/sportsbet/graph/state.py` - Added receiver_gsis_id: str field and docstring; updated request_type docstring with all 5 values
- `src/sportsbet/graph/agents.py` - Replaced _extract_odds_snapshot inline math with remove_vig_multiplicative; lazy import of vig.py; Decimal.quantize for precision
- `src/sportsbet/graph/graph.py` - Extended create_graph_with_sqlite() with 2 new params and 4 new node construction blocks

## Decisions Made

- Decimal.quantize(Decimal("0.0000000001"), ROUND_HALF_EVEN) applied to fair_probs[0] — remove_vig_multiplicative's residual correction applies to the last element only, so fair_probs[0] accumulates sub-ulp error for symmetric markets. 10dp rounding eliminates this without affecting Kelly Criterion precision (6dp sufficient).
- arbitrage_node and kinematic_node are pool-gated — both require DB access to function meaningfully. correlation_guard and aggregator are always wired (no DB dependency) so risk controls operate even in pool-less configurations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Applied Decimal.quantize() to fair_probs[0] to eliminate sub-ulp residual**
- **Found during:** Task 2 (test_extract_odds_devigged RED verification)
- **Issue:** remove_vig_multiplicative's residual correction fixes fair[-1] exactly to Decimal("1") - sum(rest), but fair[0] is computed by division and retains a sub-ulp error (0.4999...998 vs 0.5 for symmetric -110/-110 market). The plan stated "use fair_probs[0] directly — no wrapping needed" but the plan's own test asserts exact equality == Decimal("0.5").
- **Fix:** Added `fair_prob = fair_probs[0].quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_EVEN)` before constructing AgentOddsSnapshot.
- **Files modified:** src/sportsbet/graph/agents.py
- **Verification:** test_extract_odds_devigged passes with exact Decimal("0.5") comparison.
- **Committed in:** 2e06303 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Necessary for test correctness and mathematical precision. 10dp is well beyond Kelly Criterion requirements. No scope creep.

## Issues Encountered

None beyond the Decimal precision deviation documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three v1.0 audit gaps (INT-01, INT-02, INT-04) are now closed
- create_graph_with_sqlite() is production-ready with full Phase 5/6 node wiring
- EV math is now mathematically correct — implied_probability is devigged before edge calculation
- kinematic_result key is properly typed and routable in GraphState

---
*Phase: 07-production-runtime-wiring*
*Completed: 2026-03-22*
