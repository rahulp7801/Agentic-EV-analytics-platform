---
phase: 15-context-and-vig-completion
verified: 2026-03-23T00:00:00Z
status: passed
score: 3/3 must-haves verified
re_verification: false
---

# Phase 15: Context and Vig Completion Verification Report

**Phase Goal:** Complete the two deferred v1 capabilities — add NBA game-level odds ingestion to OddsAPIPoller and context agent so NBA market context flows through GraphState, and wire the Pinnacle sharp devig method as a config-selectable alternative to multiplicative devig so QUANT-02 is fully satisfied.
**Verified:** 2026-03-23T00:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | `make_context_agent` with `state["sport"]="nba"` produces a `ContextSignals` with non-None `odds_snapshot` when `OddsAPIPoller.fetch_nba_odds` is mocked | VERIFIED | `test_nba_context_agent_fetches_nba_odds` passes — `mock_nba.assert_called_once()`, `mock_nfl.assert_not_called()`, `result["context_signals"].odds_snapshot is not None` confirmed green |
| 2  | Setting `vig_method="pinnacle"` in `_extract_odds_snapshot` returns a different `implied_probability` than `vig_method="multiplicative"` on an asymmetric -200/+170 market | VERIFIED | `test_pinnacle_devig_differs_from_multiplicative` passes — `snap_power.implied_probability != snap_mult.implied_probability` and `snap_power.implied_probability > snap_mult.implied_probability` confirmed green |
| 3  | All existing NFL context agent tests continue to pass after the changes — the NBA routing is additive | VERIFIED | `tests/test_context.py` (19 tests) all green; `tests/test_vig.py` all green; full suite 161 passed, 11 skipped — no regressions |

**Score:** 3/3 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sportsbet/ingestion/odds_poller.py` | `fetch_nba_odds()` method on `OddsAPIPoller` | VERIFIED | `async def fetch_nba_odds` at line 181; mirrors `fetch_nfl_odds` with `NBA_SPORT_KEY`; budget guard, credit tracking, structlog identical |
| `src/sportsbet/config.py` | `vig_method` Literal field on `Settings` | VERIFIED | `vig_method: Literal["multiplicative", "pinnacle"] = "multiplicative"` at line 26; `from typing import Literal` import present |
| `src/sportsbet/graph/state.py` | `sport: str | None` field on `GraphState` | VERIFIED | `sport: str | None  # type: ignore[misc]` at line 140; docstring explains None/"nfl" equivalence and CTXT-04 reference |
| `src/sportsbet/graph/agents.py` | NBA routing in `make_context_agent`; `vig_method` dispatch in `_extract_odds_snapshot` | VERIFIED | `fetch_nba_odds` called at line 193; `_extract_odds_snapshot` dispatches to `remove_vig_power` at line 374; `_vig_method` resolved at construction time (line 170) |
| `tests/test_context_and_vig_completion.py` | 5 test functions covering NBA routing and vig_method dispatch | VERIFIED | All 5 functions exist and pass: `test_nba_context_agent_fetches_nba_odds`, `test_nfl_default_still_calls_fetch_nfl_odds`, `test_pinnacle_devig_differs_from_multiplicative`, `test_vig_method_multiplicative_uses_remove_vig_multiplicative`, `test_make_context_agent_reads_vig_method_from_settings` |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `agents.py make_context_agent` | `odds_poller.py fetch_nba_odds` | `state.get("sport") or "nfl" == "nba"` branch | WIRED | Line 192–193: `if sport == "nba": raw_odds = await poller.fetch_nba_odds()` — conditional branch fully implemented |
| `agents.py _extract_odds_snapshot` | `quant/vig.py remove_vig_power` | `vig_method == "pinnacle"` branch | WIRED | Lines 373–375: `if vig_method == "pinnacle": from sportsbet.quant.vig import remove_vig_power; fair_probs = remove_vig_power(raw_probs)` |
| `agents.py make_context_agent` | `config.py Settings.vig_method` | `_vig_method = vig_method if vig_method is not None else _settings.vig_method` | WIRED | Lines 164, 170: `from sportsbet.config import settings as _settings`; `_vig_method` resolved at construction time from settings when `vig_method=None` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| QUANT-02 | 15-01-PLAN.md | System converts raw sportsbook odds to implied probabilities with configurable vig removal method (multiplicative or Pinnacle sharp) | SATISFIED | `Settings.vig_method` field wires config env var to `_extract_odds_snapshot`; `vig_method="pinnacle"` dispatches to `remove_vig_power`; REQUIREMENTS.md traceability row updated to Phase 15 Complete |
| CTXT-01 | 15-01-PLAN.md | System ingests live odds asynchronously from The Odds API with a budget manager that tracks per-request cost and enforces a configurable daily API spend cap | SATISFIED | `fetch_nba_odds()` adds NBA game-level odds to `OddsAPIPoller` with identical budget guard (`BudgetExhaustedError`, `_credits_remaining < 1`), credit tracking (`x-requests-remaining` header), and async `httpx.AsyncClient` patterns; REQUIREMENTS.md row Phase 4 / Phase 15 both Complete |
| CTXT-04 | 15-01-PLAN.md | Context Agent updates a global game state JSON on binary state changes and propagates the updated state through GraphState | SATISFIED | `state.get("sport") or "nfl"` routing in `make_context_agent` sends NBA requests to `fetch_nba_odds()`; `GraphState.sport` field declared; `ContextSignals.odds_snapshot` non-None for NBA routes confirmed by test |

**Orphaned requirements check:** REQUIREMENTS.md traceability table maps QUANT-02 and CTXT-04 to Phase 15. CTXT-01 is mapped to Phase 4 (original). All three IDs declared in PLAN frontmatter are accounted for. No orphaned requirements.

---

### Anti-Patterns Found

No anti-patterns detected in modified files.

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| — | None | — | — |

---

### Human Verification Required

None. All behaviors are verifiable programmatically via the test suite.

---

### Test Results (Verified by Execution)

Full suite run produced: **161 passed, 11 skipped** (zero new failures).

Target test file: `tests/test_context_and_vig_completion.py` — 5 tests, all GREEN.
Regression files: `tests/test_context.py` (19 tests GREEN), `tests/test_vig.py` (all GREEN).

Commit hashes documented in SUMMARY verified in git log:
- `9e91457` — test stubs (TDD RED step)
- `1edd621` — production implementation (TDD GREEN step)

---

### Summary

Phase 15 goal fully achieved. Both deferred v1 capabilities are implemented, wired, and tested:

1. **NBA odds ingestion (CTXT-01 / CTXT-04):** `OddsAPIPoller.fetch_nba_odds()` added as a direct mirror of `fetch_nfl_odds()` using `NBA_SPORT_KEY`. `GraphState.sport` field declared as `str | None`. `make_context_agent` detects `state.get("sport") or "nfl"` and branches to `fetch_nba_odds()` for NBA routes. `ContextSignals.odds_snapshot` is populated (non-None) for NBA routes. All existing NFL tests unaffected — the routing is strictly additive.

2. **Pinnacle devig (QUANT-02):** `Settings.vig_method: Literal["multiplicative", "pinnacle"] = "multiplicative"` added to `config.py`. `_extract_odds_snapshot` accepts `vig_method` parameter and dispatches to `remove_vig_power` when `"pinnacle"`. `make_context_agent` resolves `_vig_method` at construction time from the explicit parameter or `settings.vig_method`. The `ValueError` guard for both-positive-odds markets remains only on the multiplicative path. Backward-compatibility verified — default behavior unchanged.

No regressions. No stubs. No orphaned code. All key links wired and test-confirmed.

---

_Verified: 2026-03-23T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
