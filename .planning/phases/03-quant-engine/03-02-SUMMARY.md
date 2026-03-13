---
phase: 03-quant-engine
plan: "02"
subsystem: quant
tags: [decimal, vig, devig, probability, kelly, american-odds, power-method, multiplicative]

# Dependency graph
requires:
  - phase: 02-agent-infrastructure
    provides: GraphState, QuantResult, EVSignal Pydantic models that will consume fair probabilities
provides:
  - american_to_raw_prob: Decimal-typed American-odds-to-raw-probability converter (no float leakage)
  - remove_vig_multiplicative: Proportional overround normalization with exact sum-to-one guarantee
  - remove_vig_power: Pinnacle sharp devig via binary search k>=1, corrects favorite-longshot bias
affects:
  - 03-03-backtest: Consumes fair probabilities for CLV calculation
  - 04-live-odds: Arbitrage agent feeds American odds into these converters before EV comparison
  - 05-ev-engine: EVSignal.kelly_fraction pipeline receives Decimal fair probs

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Decimal(str(x)) construction — never Decimal(x) from float — prevents IEEE-754 artifacts"
    - "Binary search for power devig k in range [1, 20] not (0, 1] — k>1 required for overround>1 markets"
    - "Exact sum-to-one in multiplicative devig via residual correction on last element"

key-files:
  created:
    - src/sportsbet/quant/__init__.py
    - src/sportsbet/quant/vig.py
    - tests/test_vig.py
  modified: []

key-decisions:
  - "Power devig binary search range is [1, 20] not (0, 1] — for p in (0,1), p^k < p when k>1, so overround normalization requires k>1"
  - "float() cast confined exclusively to binary search convergence loop — all return values are Decimal"
  - "Multiplicative sum-to-one achieved via residual correction: last element = 1 - sum(all_but_last) — eliminates Decimal division remainder"
  - "remove_vig_power upper bound k=20 accommodates extreme markets; typical market uses k in [1.0, 1.1]"

patterns-established:
  - "Decimal(str(american_odds)) pattern: always construct Decimal from string representation of numeric input"
  - "Binary search bounds must match domain of the function being solved — verify direction before implementing"
  - "Power devig k range: search [1, infinity) since raw probs sum > 1 requires k > 1 to compress to sum = 1"

requirements-completed: [QUANT-02]

# Metrics
duration: 5min
completed: 2026-03-13
---

# Phase 3 Plan 02: Vig Removal Probability Converter Summary

**Decimal-typed vig removal module with multiplicative normalization and Pinnacle power devig (binary search k>=1), bridging raw sportsbook American odds to fair probabilities for the Kelly pipeline.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-13T19:18:54Z
- **Completed:** 2026-03-13T19:23:20Z
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 3

## Accomplishments
- Implemented `american_to_raw_prob` with strict Decimal construction (Decimal(str(x)), never Decimal(float))
- Implemented `remove_vig_multiplicative` with overround guard and exact sum-to-one residual correction
- Implemented `remove_vig_power` with corrected binary search (k in [1, 20]) that converges to within 1e-9 of true fair probability
- All 9 test_vig.py tests pass GREEN; no regressions to prior phases

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — failing test stubs for QUANT-02** - `914e225` (test)
2. **Task 2: vig.py — implement all three functions GREEN** - `6238c1f` (feat)

_Note: TDD tasks — RED stub commit then GREEN implementation commit_

## Files Created/Modified
- `src/sportsbet/quant/__init__.py` - Quant engine sub-package init
- `src/sportsbet/quant/vig.py` - Three exported functions: american_to_raw_prob, remove_vig_multiplicative, remove_vig_power
- `tests/test_vig.py` - 9 unit tests covering all QUANT-02 requirements

## Decisions Made
- Power devig binary search searches k in [1, 20] not (0, 1] — for p in (0,1), p^k increases as k decreases, so k must exceed 1 to compress overround-inflated raw probabilities to sum=1
- Multiplicative sum-to-one guaranteed via residual correction on the last element (1 - sum(all_but_last)) rather than pure division — eliminates accumulated Decimal arithmetic remainder
- float() cast confined to binary search loop only — final k value converted back via Decimal(str(k))

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected power devig binary search direction and range**
- **Found during:** Task 2 (vig.py implementation GREEN phase)
- **Issue:** Plan's code snippet specified `lo, hi = 0.0, 1.0` with `if total > 1.0: hi = mid` — inverted logic and wrong range. For p in (0,1), p^k increases as k decreases (k toward 0 means p^0=1 for all p), so k→0 causes sum→N (number of outcomes), not toward 1. Correct k must be >1 for typical overround markets.
- **Fix:** Changed search range to `lo, hi = 1.0, 20.0` and corrected branch: `if total > 1.0: lo = mid` (need to increase k to compress probabilities)
- **Files modified:** src/sportsbet/quant/vig.py
- **Verification:** test_power_sums_to_one passes; sum within 1e-6 of Decimal('1'); test_power_favors_favorite passes
- **Committed in:** 6238c1f (Task 2 commit)

**2. [Rule 1 - Bug] Fixed multiplicative devig exact sum-to-one precision**
- **Found during:** Task 2 (vig.py implementation GREEN phase)
- **Issue:** Pure Decimal division of repeating decimal (110/210 = 0.5238...) by overround left residual ~4e-28, causing `sum(fair) == Decimal("1")` to fail
- **Fix:** Replaced last element with `1 - sum(all_but_last)` to guarantee exact sum-to-one regardless of Decimal precision context
- **Files modified:** src/sportsbet/quant/vig.py
- **Verification:** test_multiplicative_sums_to_one passes with `==` (not approximate)
- **Committed in:** 6238c1f (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (Rule 1 — logic bugs in plan's suggested code)
**Impact on plan:** Both fixes were mathematical correctness requirements. The plan's code snippet had an inverted binary search that could never converge for real markets. No scope creep.

## Issues Encountered
- Pre-existing failing test `test_quant.py::test_query_builder_parameterized` from 03-01 RED stubs — verified pre-existing before my changes, out of scope for 03-02

## User Setup Required
None - no external service configuration required. Module is pure Decimal arithmetic, no DB, no API calls.

## Next Phase Readiness
- QUANT-02 complete: `sportsbet.quant.vig` exports three functions ready for import by 03-03 backtesting and Phase 4 live odds arbitrage comparison
- EVSignal.kelly_fraction pipeline can now receive lossless Decimal fair probabilities
- No blockers

---
*Phase: 03-quant-engine*
*Completed: 2026-03-13*
