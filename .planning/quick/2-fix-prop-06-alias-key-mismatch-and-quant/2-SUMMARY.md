---
phase: quick-2
plan: 2
subsystem: prop-arbitrage, context-agent
tags: [bug-fix, prop-ev, alias-map, stat-type, nfl, tdd]
dependency_graph:
  requires:
    - src/sportsbet/prop/arbitrage.py (_PROP_TYPE_ALIAS_MAP)
    - src/sportsbet/ingestion/odds_poller.py (NFL_PROP_MARKETS)
    - src/sportsbet/graph/agents.py (make_context_agent)
    - src/sportsbet/graph/state.py (GraphState.stat_type, GraphState.prop_filters)
  provides:
    - Corrected NFL prop alias map — matched_snapshot no longer silently None for pass/rush/rec props
    - context_agent always returns stat_type key — quant_agent routing no longer defaults to "passing"
  affects:
    - tests/test_prop_arbitrage.py (TestPropAliasMapKeys added; Phase 23 fixtures corrected)
    - tests/test_context.py (TestContextAgentStatType added)
tech_stack:
  added: []
  patterns:
    - Module-level frozenset constants for prop-type category lookup (_RUSHING_PROP_TYPES, _RECEIVING_PROP_TYPES)
    - _infer_stat_type pure function following _extract_situational_params pattern
    - TDD: RED (failing test) -> GREEN (implementation) -> commit per task
key_files:
  created: []
  modified:
    - src/sportsbet/prop/arbitrage.py
    - src/sportsbet/graph/agents.py
    - tests/test_prop_arbitrage.py
    - tests/test_context.py
decisions:
  - "_PROP_TYPE_ALIAS_MAP NFL values must match NFL_PROP_MARKETS keys exactly — player_pass_yds not player_pass_yards"
  - "Phase 23 test fixtures used stale incorrect keys (player_pass_yards) — updated to player_pass_yds as Rule 1 auto-fix"
  - "_infer_stat_type placed as module-level private function (not closure-local) — consistent with _extract_situational_params pattern"
  - "rush_tds and rec_tds added to _PROP_TYPE_ALIAS_MAP — present in NFL_PROP_MARKETS but missing from original map"
metrics:
  duration: "~8 min"
  completed: "2026-03-27"
  tasks_completed: 2
  files_modified: 4
---

# Quick Task 2: Fix PROP-06 Alias Key Mismatch and QUANT-03 stat_type Routing

**One-liner:** NFL prop alias map corrected to match `NFL_PROP_MARKETS` keys exactly (`player_pass_yds`, `player_rush_yds`, `player_reception_yds`); `context_agent` now always writes `stat_type` inferred from `prop_filters.prop_type`.

## What Was Fixed

### PROP-06: `_PROP_TYPE_ALIAS_MAP` key mismatches

Three NFL entries in `_PROP_TYPE_ALIAS_MAP` mapped to incorrect Odds API market keys that did not match any key in `NFL_PROP_MARKETS`. This caused `matched_snapshot` to always be `None` for passing, rushing, and receiving props — silently falling back to the h2h EV path.

**Before (wrong):**
```python
"pass_yds": "player_pass_yards",   # NFL_PROP_MARKETS has "player_pass_yds"
"rush_yds": "player_rush_yards",   # NFL_PROP_MARKETS has "player_rush_yds"
"rec_yds": "player_receiving_yards",  # NFL_PROP_MARKETS has "player_reception_yds"
```

**After (correct):**
```python
"pass_yds": "player_pass_yds",
"rush_yds": "player_rush_yds",
"rec_yds": "player_reception_yds",
"rush_tds": "player_rush_tds",     # added — was missing
"rec_tds": "player_reception_tds", # added — was missing
```

### QUANT-03: `context_agent` stat_type inference

`context_agent` never wrote `stat_type` into its return dict. `quant_agent` reads `state.get("stat_type") or "passing"` (quick-1 fix) but always defaulted to `"passing"` for rushing/receiving routes because the key was never populated.

Added:
- `_RUSHING_PROP_TYPES: frozenset[str]` — module-level constant
- `_RECEIVING_PROP_TYPES: frozenset[str]` — module-level constant
- `_infer_stat_type(prop_filters) -> str | None` — pure function, module-level private
- `context_agent` return dict now includes `"stat_type": _infer_stat_type(state.get("prop_filters"))`

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix _PROP_TYPE_ALIAS_MAP receiving yards key mismatch | 6fa214e | arbitrage.py, test_prop_arbitrage.py |
| 2 | context_agent infers and writes stat_type from prop_filters | 3b747ab | agents.py, test_context.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Phase 23 test fixtures used stale incorrect Odds API keys**
- **Found during:** Task 1 verification (full test suite run after alias map fix)
- **Issue:** Phase 23 `TestProp06PlayerPropSnapshot` and `TestProp06CommensurableEV` fixtures used `player_pass_yards` and `player_rush_yards` as `prop_type` values — exactly the wrong keys that the PROP-06 fix corrected. After fixing the alias map, those tests failed because the snapshot `prop_type` no longer matched.
- **Fix:** Updated all Phase 23 test fixture `prop_type` values to the correct Odds API keys: `player_pass_yds`, `player_rush_yds`. Also updated `test_no_type_match_returns_no_signal` to use `player_rush_yds`.
- **Files modified:** `tests/test_prop_arbitrage.py`
- **Commit:** bfb56f8

## Tests Added

- `TestPropAliasMapKeys` (3 tests) in `tests/test_prop_arbitrage.py`
  - `test_rec_yds_maps_to_player_reception_yds`
  - `test_all_nfl_alias_values_in_nfl_prop_markets`
  - `test_nba_keys_not_in_nfl_prop_markets`

- `TestContextAgentStatType` (6 tests) in `tests/test_context.py`
  - `test_stat_type_rushing_for_rush_yds`
  - `test_stat_type_receiving_for_rec_yds`
  - `test_stat_type_receiving_for_rec_tds`
  - `test_stat_type_passing_for_pass_yds`
  - `test_stat_type_none_for_none_prop_filters`
  - `test_stat_type_none_when_prop_filters_key_absent`

## Verification

```
232 passed, 11 skipped, 2 xfailed — zero regressions
```

## Self-Check: PASSED

- `src/sportsbet/prop/arbitrage.py` — exists, `_PROP_TYPE_ALIAS_MAP` corrected
- `src/sportsbet/graph/agents.py` — exists, `_infer_stat_type` added, `stat_type` in return
- `tests/test_prop_arbitrage.py` — exists, `TestPropAliasMapKeys` present
- `tests/test_context.py` — exists, `TestContextAgentStatType` present
- Commits: `6fa214e`, `3b747ab`, `bfb56f8` — all present in git log
