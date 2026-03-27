---
phase: quick-2
plan: 2
type: execute
wave: 1
depends_on: []
files_modified:
  - src/sportsbet/prop/arbitrage.py
  - src/sportsbet/graph/agents.py
  - tests/test_prop_arbitrage.py
  - tests/test_context.py
autonomous: true
requirements: [PROP-06, QUANT-03]

must_haves:
  truths:
    - "NFL receiving yard props match against stored PlayerPropSnapshot rows (matched_snapshot is not None)"
    - "context_agent return dict includes stat_type='rushing' when prop_filters contains a rushing prop_type"
    - "context_agent return dict includes stat_type='receiving' when prop_filters contains a receiving prop_type"
    - "context_agent returns stat_type=None for non-prop (game-level) queries without crashing"
  artifacts:
    - path: "src/sportsbet/prop/arbitrage.py"
      provides: "Corrected _PROP_TYPE_ALIAS_MAP with player_reception_yds key for rec_yds"
    - path: "src/sportsbet/graph/agents.py"
      provides: "context_agent return dict always includes stat_type key"
  key_links:
    - from: "src/sportsbet/prop/arbitrage.py _PROP_TYPE_ALIAS_MAP"
      to: "src/sportsbet/ingestion/odds_poller.py NFL_PROP_MARKETS"
      via: "normalized_prop_type lookup at match time"
      pattern: "_PROP_TYPE_ALIAS_MAP.get\\(target_prop_type"
    - from: "src/sportsbet/graph/agents.py context_agent return"
      to: "src/sportsbet/graph/state.py GraphState.stat_type"
      via: "partial state dict merge in LangGraph"
      pattern: "stat_type.*rushing|stat_type.*receiving"
---

<objective>
Fix two integration gaps identified in the v1.0 milestone audit:

1. PROP-06 — `_PROP_TYPE_ALIAS_MAP["rec_yds"]` maps to `"player_receiving_yards"` but
   `odds_poller.NFL_PROP_MARKETS` stores `"player_reception_yds"`. The mismatch means
   `matched_snapshot` is always `None` for NFL receiving yard props, causing fallback to
   the h2h EV path instead of the prop-specific path.

2. QUANT-03 — `context_agent()` never writes `stat_type` into its return dict. `quant_agent`
   reads `state.get("stat_type") or "passing"` (quick-1 fix), but always defaults to
   `"passing"` for rushing/receiving prop routes because context_agent never populates the
   field. Fix: infer stat_type from `prop_filters` at context_agent return time.

Purpose: Correct silent data-path failures that cause wrong EV calculations for NFL
         rushing/receiving props without raising any errors.
Output: Two patched source files + regression tests for each fix.
</objective>

<execution_context>
@C:/Users/rahul/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/rahul/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/1-fix-quant-03-stat-type-routing-and-quant/1-SUMMARY.md

<interfaces>
<!-- Key constants and patterns the executor needs. -->

From src/sportsbet/ingestion/odds_poller.py (line 36-40):
```python
NFL_PROP_MARKETS = (
    "player_pass_yds,player_pass_tds,player_rush_yds,"
    "player_rush_tds,player_reception_yds,player_reception_tds,"
    "player_receptions"
)
```
Note: The NFL market key for receiving yards is `"player_reception_yds"` (NOT `"player_receiving_yards"`).

From src/sportsbet/prop/arbitrage.py (line 42-52) — CURRENT (WRONG):
```python
_PROP_TYPE_ALIAS_MAP: dict[str, str] = {
    "pass_yds": "player_pass_yards",
    "rush_yds": "player_rush_yards",
    "rec_yds": "player_receiving_yards",   # <-- BUG: stored key is "player_reception_yds"
    "pass_tds": "player_pass_tds",
    "receptions": "player_receptions",
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "pra": "player_pra",
}
```

From src/sportsbet/prop/query_builder.py PROP_COLUMN_MAP — prop_type category groups:
```python
# NFL rushing: "rush_yds", "rush_tds", "carries"
# NFL receiving: "rec_yds", "rec_tds", "receptions", "targets"
# NFL passing: "pass_yds", "pass_tds", "completions", "attempts"
```

From src/sportsbet/prop/agents.py (line 48):
```python
RECEIVING_PROPS: frozenset[str] = frozenset({"rec_yds", "rec_tds", "receptions"})
```

From src/sportsbet/graph/state.py GraphState fields:
```python
prop_filters: dict[str, Any] | None   # None for non-prop routes
stat_type: str | None                  # "passing" | "rushing" | "receiving" | None
request_type: str
```

From src/sportsbet/graph/agents.py context_agent return (line 364-368) — CURRENT (MISSING stat_type):
```python
return {
    "context_signals": signals,
    "situational_params": situational_params,
    "player_prop_snapshots": _prop_snapshots if _prop_snapshots else None,
}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Fix _PROP_TYPE_ALIAS_MAP receiving yards key mismatch</name>
  <files>src/sportsbet/prop/arbitrage.py, tests/test_prop_arbitrage.py</files>
  <behavior>
    - Test 1: _PROP_TYPE_ALIAS_MAP["rec_yds"] == "player_reception_yds" (matches NFL_PROP_MARKETS key)
    - Test 2: Verify no other NFL entries in _PROP_TYPE_ALIAS_MAP diverge from NFL_PROP_MARKETS — pass_yds maps to "player_pass_yards" but NFL_PROP_MARKETS has "player_pass_yds"; rush_yds maps to "player_rush_yards" but NFL_PROP_MARKETS has "player_rush_yds" — audit all NFL keys for the same pattern
    - Test 3: NBA keys in the map (points, rebounds, assists, pra) are not in NFL_PROP_MARKETS — no change needed for those
  </behavior>
  <action>
    Step 1 (RED): Add a test class `TestPropAliasMapKeys` in tests/test_prop_arbitrage.py that:
    - Imports `_PROP_TYPE_ALIAS_MAP` from `sportsbet.prop.arbitrage`
    - Imports `NFL_PROP_MARKETS` from `sportsbet.ingestion.odds_poller`
    - Asserts `_PROP_TYPE_ALIAS_MAP["rec_yds"] == "player_reception_yds"`
    - Audits all map values that should match NFL_PROP_MARKETS keys: parse NFL_PROP_MARKETS string into a set and assert each NFL-related map value is present in that set (NBA keys: points, rebounds, assists, pra are NBA — skip them in this assertion)

    Step 2 (AUDIT): Cross-reference _PROP_TYPE_ALIAS_MAP values against NFL_PROP_MARKETS string:
    NFL_PROP_MARKETS contains: player_pass_yds, player_pass_tds, player_rush_yds, player_rush_tds, player_reception_yds, player_reception_tds, player_receptions
    Current map values for NFL props:
    - pass_yds -> "player_pass_yards"  (NFL_PROP_MARKETS has "player_pass_yds" — MISMATCH)
    - rush_yds -> "player_rush_yards"  (NFL_PROP_MARKETS has "player_rush_yds" — MISMATCH)
    - rec_yds  -> "player_receiving_yards" (NFL_PROP_MARKETS has "player_reception_yds" — MISMATCH)
    - pass_tds -> "player_pass_tds"    (matches)
    - receptions -> "player_receptions" (matches)

    Step 3 (GREEN): Fix all mismatched NFL entries in _PROP_TYPE_ALIAS_MAP:
    ```python
    _PROP_TYPE_ALIAS_MAP: dict[str, str] = {
        "pass_yds": "player_pass_yds",       # was player_pass_yards
        "rush_yds": "player_rush_yds",        # was player_rush_yards
        "rec_yds": "player_reception_yds",    # was player_receiving_yards
        "pass_tds": "player_pass_tds",
        "receptions": "player_receptions",
        "points": "player_points",
        "rebounds": "player_rebounds",
        "assists": "player_assists",
        "pra": "player_pra",
    }
    ```
    Also add entries for NFL props present in NFL_PROP_MARKETS but missing from the map:
    - "rush_tds" -> "player_rush_tds"
    - "rec_tds"  -> "player_reception_tds"

    Do NOT change the normalization call at line ~177 or any downstream consumer.
    The fix is purely the dict literal values.
  </action>
  <verify>
    <automated>cd C:/Users/rahul/ucla/pp/sportsbet && python -m pytest tests/test_prop_arbitrage.py::TestPropAliasMapKeys -xvs</automated>
  </verify>
  <done>All _PROP_TYPE_ALIAS_MAP NFL values exactly match the corresponding keys in NFL_PROP_MARKETS. rec_yds -> "player_reception_yds". Tests green.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: context_agent infers and writes stat_type from prop_filters</name>
  <files>src/sportsbet/graph/agents.py, tests/test_context.py</files>
  <behavior>
    - Test 1: When state["prop_filters"] = {"prop_type": "rush_yds"}, context_agent return dict includes {"stat_type": "rushing"}
    - Test 2: When state["prop_filters"] = {"prop_type": "rec_yds"}, return dict includes {"stat_type": "receiving"}
    - Test 3: When state["prop_filters"] = {"prop_type": "rec_tds"}, return dict includes {"stat_type": "receiving"}
    - Test 4: When state["prop_filters"] = {"prop_type": "pass_yds"}, return dict includes {"stat_type": "passing"}
    - Test 5: When state["prop_filters"] is None (non-prop game query), return dict includes {"stat_type": None}
    - Test 6: When state has no "prop_filters" key at all, return dict includes {"stat_type": None} (no KeyError)
  </behavior>
  <action>
    Step 1 (RED): Add a test class `TestContextAgentStatType` in tests/test_context.py that
    patches `OddsAPIPoller`, `InjuryWeatherScraper`, and `asyncpg.create_pool` (or the
    existing pool fixture pattern used in the file). For each behavior test, call the
    context_agent closure directly with a mock state containing the relevant prop_filters
    value, then assert the returned dict has the correct stat_type value.

    Follow the existing test patterns in test_context.py for mocking make_context_agent.

    Step 2 (GREEN): Add a helper function `_infer_stat_type` inside the make_context_agent
    closure body (or as a module-level private function) in agents.py:

    ```python
    _RUSHING_PROP_TYPES: frozenset[str] = frozenset({"rush_yds", "rush_tds", "carries"})
    _RECEIVING_PROP_TYPES: frozenset[str] = frozenset({"rec_yds", "rec_tds", "receptions", "targets"})

    def _infer_stat_type(prop_filters: dict | None) -> str | None:
        """Infer quant stat_type from prop_filters.prop_type. Returns None for non-prop routes."""
        if not prop_filters:
            return None
        pt = prop_filters.get("prop_type")
        if pt in _RUSHING_PROP_TYPES:
            return "rushing"
        if pt in _RECEIVING_PROP_TYPES:
            return "receiving"
        if pt is not None:
            return "passing"  # Default for any other prop_type (pass_yds, pass_tds, NBA props, etc.)
        return None
    ```

    Place `_RUSHING_PROP_TYPES` and `_RECEIVING_PROP_TYPES` as module-level constants (after
    existing imports, before make_context_agent). Place `_infer_stat_type` as a module-level
    private function (same pattern as existing `_extract_situational_params`).

    Step 3: Update the context_agent return dict at line ~364 to include stat_type:
    ```python
    return {
        "context_signals": signals,
        "situational_params": situational_params,
        "player_prop_snapshots": _prop_snapshots if _prop_snapshots else None,
        "stat_type": _infer_stat_type(state.get("prop_filters")),
    }
    ```

    Do NOT change any other part of make_context_agent. The field is Optional[str] in
    GraphState so returning None is valid and safe for all non-prop routes.
  </action>
  <verify>
    <automated>cd C:/Users/rahul/ucla/pp/sportsbet && python -m pytest tests/test_context.py::TestContextAgentStatType -xvs</automated>
  </verify>
  <done>context_agent return dict always contains "stat_type" key. Value is "rushing"/"receiving"/"passing" for prop routes and None for non-prop routes. Full test suite still passes.</done>
</task>

</tasks>

<verification>
Run the full test suite to confirm no regressions:

```bash
cd C:/Users/rahul/ucla/pp/sportsbet && python -m pytest tests/test_prop_arbitrage.py tests/test_context.py -x --tb=short
```

Then run a broader smoke pass:

```bash
cd C:/Users/rahul/ucla/pp/sportsbet && python -m pytest tests/ -x --tb=short -q
```
</verification>

<success_criteria>
- `_PROP_TYPE_ALIAS_MAP` NFL values all match keys present in NFL_PROP_MARKETS (no silent alias miss)
- `rec_yds` correctly maps to `"player_reception_yds"` — matched_snapshot no longer returns None for NFL receiving props
- `context_agent` return dict includes `stat_type` on every code path
- `stat_type` is "rushing" for rush prop routes, "receiving" for receiving prop routes, "passing" for passing/NBA prop routes, None for non-prop game queries
- All existing tests pass (zero regressions)
</success_criteria>

<output>
After completion, create `.planning/quick/2-fix-prop-06-alias-key-mismatch-and-quant/2-SUMMARY.md`
following the standard summary template.
</output>
