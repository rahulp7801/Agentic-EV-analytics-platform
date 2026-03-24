---
phase: 15-context-and-vig-completion
plan: "01"
subsystem: context-agent / odds-ingestion / config
tags: [nba, context-agent, vig, odds-poller, config, tdd]
dependency_graph:
  requires: []
  provides:
    - OddsAPIPoller.fetch_nba_odds()
    - Settings.vig_method Literal field
    - GraphState.sport field
    - NBA routing in make_context_agent
    - vig_method dispatch in _extract_odds_snapshot
  affects:
    - src/sportsbet/ingestion/odds_poller.py
    - src/sportsbet/config.py
    - src/sportsbet/graph/state.py
    - src/sportsbet/graph/agents.py
tech_stack:
  added: []
  patterns:
    - Closure factory reads Settings at construction time (not invocation time) for vig_method
    - Sport routing via state.get("sport") or "nfl" — additive, no required field
    - TDD RED/GREEN — test stubs committed before production code
key_files:
  created:
    - tests/test_context_and_vig_completion.py
  modified:
    - src/sportsbet/ingestion/odds_poller.py (+44 lines)
    - src/sportsbet/config.py (+8 lines)
    - src/sportsbet/graph/state.py (+7 lines)
    - src/sportsbet/graph/agents.py (+40 lines, net)
decisions:
  - vig_method resolved at make_context_agent construction time (not each invocation) — stored in _vig_method closure variable; consistent with existing _sync_engine_cache lazy init pattern
  - sport detected at invocation time via state.get("sport") or "nfl" — keeps field optional, never required (INFRA-01 pattern)
  - ValueError guard for both-positive-odds markets stays ONLY on multiplicative path — remove_vig_power has no ValueError path
  - fetch_nba_odds mirrors fetch_nfl_odds exactly with NBA_SPORT_KEY substitution — no new abstractions
metrics:
  duration: "5 minutes"
  completed_date: "2026-03-24"
  tasks_completed: 2
  files_modified: 5
requirements-completed: [QUANT-02, CTXT-01, CTXT-04]
---

# Phase 15 Plan 01: Context and Vig Completion Summary

NBA game-level odds ingestion wired to OddsAPIPoller, make_context_agent routes sport="nba" state to fetch_nba_odds(), and Pinnacle power devig made config-selectable via Settings.vig_method.

## What Was Built

### OddsAPIPoller.fetch_nba_odds()
Added to `src/sportsbet/ingestion/odds_poller.py` as a mirror of `fetch_nfl_odds()` with `NBA_SPORT_KEY` substitution in the URL and assert message. Full budget guard (BudgetExhaustedError), x-requests-remaining header tracking, and structlog instrumentation are preserved.

### Settings.vig_method
Added `vig_method: Literal["multiplicative", "pinnacle"] = "multiplicative"` to `Settings` in `src/sportsbet/config.py`. Requires `from typing import Literal` import (added). Default value preserves existing behavior for all callers that don't set the env var.

### GraphState.sport
Added `sport: str | None` as the last field in `GraphState` TypedDict in `src/sportsbet/graph/state.py`. Includes docstring entry explaining None/"nfl" equivalence and CTXT-04 reference. Access pattern is `state.get("sport")` — never required.

### NBA Sport Routing in make_context_agent
- New `vig_method: str | None = None` parameter on `make_context_agent` signature
- `_vig_method` resolved at construction time: `vig_method if vig_method is not None else _settings.vig_method`
- Inside the async closure: `sport = state.get("sport") or "nfl"` detects NBA vs NFL
- OddsAPIPoller block branches: `if sport == "nba": raw_odds = await poller.fetch_nba_odds()` else `fetch_nfl_odds()`
- `_extract_odds_snapshot(raw_odds, game_id, vig_method=_vig_method)` passes resolved vig method

### Vig Dispatch in _extract_odds_snapshot
- New `vig_method: str = "multiplicative"` parameter added to signature
- `if vig_method == "pinnacle": from sportsbet.quant.vig import remove_vig_power; fair_probs = remove_vig_power(raw_probs)`
- Else: original `try: remove_vig_multiplicative except ValueError: fair_probs = raw_probs` path preserved
- Docstring updated to document both methods

## Test Results

```
161 passed, 11 skipped
```

- New tests: 5 (all GREEN after Task 2 implementation)
- Regression: test_context.py 19 tests — all GREEN (NFL routing unchanged)
- Regression: test_vig.py — all GREEN

### New Test Functions
1. `test_nba_context_agent_fetches_nba_odds` — CTXT-04: fetch_nba_odds called for sport="nba"; odds_snapshot is non-None
2. `test_nfl_default_still_calls_fetch_nfl_odds` — regression guard: NFL default path unchanged
3. `test_pinnacle_devig_differs_from_multiplicative` — QUANT-02: power devig produces higher favorite probability on -200/+170 fixture
4. `test_vig_method_multiplicative_uses_remove_vig_multiplicative` — backward compat: "multiplicative" matches direct remove_vig_multiplicative call
5. `test_make_context_agent_reads_vig_method_from_settings` — vig_method="pinnacle" forwarded to _extract_odds_snapshot via spy

## Deviations from Plan

None — plan executed exactly as written.

## Requirements Satisfied

- CTXT-01: NBA context agent fetches and populates odds_snapshot for NBA routes
- CTXT-04: state["sport"]="nba" routes to fetch_nba_odds(), state without sport defaults to NFL
- QUANT-02: Pinnacle power devig (remove_vig_power) is config-selectable via Settings.vig_method and make_context_agent vig_method parameter

## Self-Check: PASSED

All files present. All commits (9e91457, 1edd621) verified in git log.
