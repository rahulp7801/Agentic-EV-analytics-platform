---
phase: 23-prop-ev-fix
plan: 01
subsystem: arbitrage
tags: [pydantic, langgraph, kelly, ev, player-props, decimal, odds-api]

# Dependency graph
requires:
  - phase: 13-player-prop-arbitrage-and-pipeline-wiring
    provides: make_prop_arbitrage_agent closure, EVSignal, PropResult, GraphState prop_type/prop_line fields
  - phase: 14-prop-integration-gap-closure
    provides: PlayerPropSnapshotCreate, write_player_prop_snapshot, sport=None auto-detect
  - phase: 18-situational-game-log-prop-queries
    provides: situational_params field pattern in GraphState / context_agent return dict
provides:
  - player_prop_snapshots field in GraphState TypedDict (list[Any] | None)
  - _prop_snapshots collected in context_agent Step 1c, returned in partial state dict
  - _PROP_TYPE_ALIAS_MAP in prop/arbitrage.py (PropParams shorthand -> Odds API market key)
  - Guard 2a snapshot match path in PropArbitrageAgent (prop_type + line match -> implied_prob)
  - Guard 2b fallback to context_signals.odds_snapshot for non-prop routes
  - TestProp06PlayerPropSnapshot (2 tests), TestProp06NoSnapshotGuard (3 tests), TestProp06CommensurableEV (3 tests)
affects:
  - phase: 24-prop-ev-fix (any follow-on plans building on commensurable EV)
  - PropArbitrageAgent callers setting player_prop_snapshots in GraphState

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Snapshot match path: Guard 2a matches PlayerPropSnapshot on (normalized_prop_type, line) before Guard 2b odds_snapshot fallback"
    - "_PROP_TYPE_ALIAS_MAP module-level dict bridges PropParams Literal shorthands to Odds API market key format"
    - "_prop_snapshots initialized before try block in context_agent to ensure always-in-scope at return step"

key-files:
  created: []
  modified:
    - tests/test_prop_arbitrage.py
    - src/sportsbet/graph/state.py
    - src/sportsbet/graph/agents.py
    - src/sportsbet/prop/arbitrage.py

key-decisions:
  - "Phase 23 PROP-06: matched_snapshot.implied_probability used directly (vig-inclusive Decimal) rather than re-deriving via american_to_raw_prob + devig — multiplicative/power devig requires both sides of a market co-located, which is not guaranteed for single-side snapshots"
  - "Phase 23 PROP-06: _PROP_TYPE_ALIAS_MAP resolves 9 PropParams shorthand Literals to Odds API market key format at match time — no schema migration needed, purely in-memory normalization"
  - "Phase 23 PROP-06: line_match uses Decimal == Decimal comparison — both snap.line and target_line are Decimal or None, no float promotion risk"
  - "Phase 23 PROP-06: Guard 2b (odds_snapshot fallback) preserved for non-prop routes — ensures backward compatibility with existing arbitrage pipeline tests"

patterns-established:
  - "Snapshot match pattern: state.get('player_prop_snapshots') -> iterate -> _PROP_TYPE_ALIAS_MAP.get(target, target) -> snap.prop_type == normalized AND snap.line == target_line"
  - "Alias map at module level: dict[str, str] for prop_type normalization — single source of truth, O(1) lookup"

requirements-completed: [PROP-06]

# Metrics
duration: 12min
completed: 2026-03-26
---

# Phase 23 Plan 01: PROP-06 EV Fix Summary

**PropArbitrageAgent now computes EV against a matched PlayerPropSnapshot implied_probability (prop-specific), replacing the mathematically incommensurable h2h moneyline probability from context_signals.odds_snapshot**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-03-26T21:00:00Z
- **Completed:** 2026-03-26T21:10:12Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 4

## Accomplishments
- Added `player_prop_snapshots: list[Any] | None` field to GraphState TypedDict with full docstring
- Wired `_prop_snapshots` collection into context_agent Step 1c (before write, initialized outside try block) and returned in partial state dict
- Implemented `_PROP_TYPE_ALIAS_MAP` (9 entries) bridging PropParams Literal shorthands to Odds API market key format
- Implemented Guard 2a (snapshot match on prop_type + line) and Guard 2b (odds_snapshot fallback) in PropArbitrageAgent
- 8 new tests across 3 classes (TestProp06PlayerPropSnapshot, TestProp06NoSnapshotGuard, TestProp06CommensurableEV); all 18 prop arbitrage tests GREEN; full suite 214 passed, 11 skipped, 2 xfailed

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — Add failing tests for PROP-06 snapshot match path** - `5dee613` (test)
2. **Task 2: Wave 1 — Wire player_prop_snapshots through state and implement snapshot match** - `8353751` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD tasks — test commit (RED) then feat commit (GREEN)_

## Files Created/Modified
- `tests/test_prop_arbitrage.py` - Added _SNAPSHOT_IMPORT_OK guard, updated _make_nfl_state/_make_nba_state with player_prop_snapshots kwarg, added 3 new test classes (8 tests total)
- `src/sportsbet/graph/state.py` - Added player_prop_snapshots: list[Any] | None field with docstring to GraphState TypedDict
- `src/sportsbet/graph/agents.py` - Added _prop_snapshots=[] before Step 1c try block; append snap before write; include player_prop_snapshots in return dict
- `src/sportsbet/prop/arbitrage.py` - Added _PROP_TYPE_ALIAS_MAP (9 entries); replaced Guard 2 with Guard 2a (snapshot match) + Guard 2b (odds_snapshot fallback)

## Decisions Made
- `matched_snapshot.implied_probability` used directly (stored vig-inclusive Decimal) rather than re-deriving via devig — single-side snapshots cannot be devigged without the opposing side
- `_PROP_TYPE_ALIAS_MAP` at module level for O(1) normalization; 9 entries cover all PropParams Literal shorthands
- `line_match` uses Decimal == Decimal comparison, no float promotion
- Guard 2b preserved for backward compatibility — non-prop routes still use odds_snapshot

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation matched plan specification without surprises.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- PROP-06 EV fix complete: prop EV outputs are now mathematically commensurable (prop probability vs prop probability)
- player_prop_snapshots flows through context_agent -> GraphState -> PropArbitrageAgent
- Existing PROP-06/07/E2E tests all GREEN; no regressions
- Phase 23 Plan 02 (if any) can build on snapshot match infrastructure

---
*Phase: 23-prop-ev-fix*
*Completed: 2026-03-26*

## Self-Check: PASSED

- FOUND: tests/test_prop_arbitrage.py
- FOUND: src/sportsbet/graph/state.py
- FOUND: src/sportsbet/graph/agents.py
- FOUND: src/sportsbet/prop/arbitrage.py
- FOUND: .planning/phases/23-prop-ev-fix/23-01-SUMMARY.md
- FOUND: commit 5dee613 (test RED phase)
- FOUND: commit 8353751 (feat GREEN phase)
