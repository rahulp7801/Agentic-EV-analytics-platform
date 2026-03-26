# Phase 19: Critical Integration Fixes - Research

**Researched:** 2026-03-25
**Domain:** Python agent wiring — LangGraph GraphState bridge fixes, Pydantic model field propagation
**Confidence:** HIGH

## Summary

Phase 19 closes exactly two integration gaps that block clean v1.0 milestone sign-off. Both gaps are surgical: no new modules, no schema changes, no new Pydantic models. The fixes are confined to two existing files — `src/sportsbet/graph/agents.py` (INT-2, one literal → variable substitution) and `src/sportsbet/prop/agents.py` (INT-1, reads `situational_params` from state and forwards `teammate_out_signals` → `PropParams.teammate_out` before building the query).

The underlying infrastructure is already complete. `PropParams.teammate_out` field, the `PropQueryBuilder` and `NBAQueryBuilder` conditional WHERE clauses, and the `situational_params` key in GraphState were all implemented in Phase 18 and are currently passing all 188 tests. The Phase 18 SC-3/SC-4 situational query machinery is wired and proven correct — it is simply never reached in automated runs because `make_prop_quant_agent` never reads `situational_params` from state. Similarly, `fetch_player_props(sport)` is correctly called with the dynamic `sport` variable, but the `PlayerPropSnapshotCreate` call four lines later still hard-codes `sport="nfl"`, silently corrupting every NBA prop snapshot row.

**Primary recommendation:** Two targeted edits only. Do not restructure, refactor, or add new abstractions. Each fix must be accompanied by a narrowly scoped regression test.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-01 | System ingests live NFL and NBA player prop odds from The Odds API and writes timestamped `PlayerPropSnapshot` rows to PostgreSQL | INT-2 fix passes the resolved `sport` variable (not literal `"nfl"`) to `PlayerPropSnapshotCreate`, so NBA snapshots are stored with `sport="nba"`. Completing this closes the partial PROP-01 gap documented in the audit. |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | already installed | Async PostgreSQL pool used by all agent closures | All agent closures bind an asyncpg.Pool at construction time |
| Pydantic v2 | already installed | PropParams validation gate — all LLM/state-sourced inputs validated before SQL | Non-negotiable per CLAUDE.md; strict=True on PropParams |
| structlog | already installed | Structured logging inside agent closures | Matches existing log.info / log.error call pattern in both files |
| pytest + pytest-asyncio | already installed | Regression test harness | 188 tests currently passing; new tests follow existing patterns |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock (stdlib) | stdlib | Patching module-level imports (OddsAPIPoller, write_player_prop_snapshot) in agents.py tests | Required: closure-scoped imports cannot be patched; module-level names can |

**Installation:** None required. All dependencies are already installed.

---

## Architecture Patterns

### Existing File Structure (no changes)
```
src/sportsbet/
├── graph/
│   └── agents.py          # INT-2 fix: line 304 sport="nfl" → sport=sport
├── prop/
│   └── agents.py          # INT-1 fix: read situational_params, forward to PropParams
tests/
├── test_context_agent_params.py        # existing — context agent injects situational_params
├── test_prop_params_situational.py     # existing — PropParams.teammate_out field contract
├── test_prop_query_builder_situational.py  # existing — query builder conditional WHERE
└── (new test file for Phase 19 fixes)
```

### Pattern 1: INT-2 Fix — One-Line Variable Substitution

**What:** `PlayerPropSnapshotCreate(sport="nfl", ...)` at `src/sportsbet/graph/agents.py` line 304 uses a string literal. The variable `sport` is resolved at line 219 as `state.get("sport") or "nfl"`. The fix is to substitute the variable for the literal.

**Exact location:**
```python
# Line 219 — sport variable already resolved correctly:
sport = state.get("sport") or "nfl"  # "nba" for NBA, "nfl" for NFL

# Line 304 — BEFORE (bug):
snap = PlayerPropSnapshotCreate(
    sport="nfl",          # <-- hardcoded literal; must be variable
    game_id=event_data.get("id"),
    ...
)

# Line 304 — AFTER (fix):
snap = PlayerPropSnapshotCreate(
    sport=sport,          # <-- resolved variable from line 219
    game_id=event_data.get("id"),
    ...
)
```

**Scope:** One character change in one line. `sport` is already in scope inside `context_agent` closure at line 304. No new imports. No parameter changes.

### Pattern 2: INT-1 Fix — situational_params → PropParams Bridge

**What:** `make_prop_quant_agent` in `src/sportsbet/prop/agents.py` must read `state.get("situational_params", {})` (or `None`) and extract `teammate_out_signals` from it, then pass those as `PropParams.teammate_out`. This activates the Phase 18 conditional WHERE clause that is already implemented in `PropQueryBuilder.build()` and `NBAQueryBuilder.build()`.

**Data flow (already proven):**
```
context_agent (graph/agents.py line 351):
    situational_params = _extract_situational_params(signals)
    # Returns: {"teammate_out_signals": ["Anthony Davis", ...]} or None
    return {"context_signals": signals, "situational_params": situational_params}

GraphState.situational_params (state.py line 146):
    situational_params: dict[str, Any] | None
    # "teammate_out_signals" list for use by PropQueryBuilder in Plan 03

make_prop_quant_agent (prop/agents.py — MISSING BRIDGE):
    # Currently reads: receiver_gsis_id, season, game_id, prop_type, prop_line, prop_filters
    # Missing: does NOT read situational_params at all
    # PropParams.teammate_out is always None — conditional WHERE never fires

PropParams (graph/models.py line 198):
    teammate_out: Optional[list[str]] = None
    # Already defined. Phase 18 SC-3. Backward compatible.

PropQueryBuilder.build() / NBAQueryBuilder.build():
    if params.teammate_out:
        # appends AND EXISTS (...injury_reports INTERVAL window...)
    # Already implemented and tested. Waiting for input.
```

**Fix pattern for `make_prop_quant_agent`:**
```python
# In the inner async def prop_quant_agent(state):
# Add after existing state reads:
situational: dict = state.get("situational_params") or {}  # type: ignore[union-attr]
teammate_out: list[str] | None = situational.get("teammate_out_signals") or None

params = PropParams(
    game_id=game_id,
    player_id=player_id,
    season=season,
    sport="nfl",
    prop_type=prop_type,
    line=line,
    filters=prop_filters if prop_filters else {},
    teammate_out=teammate_out,   # <-- NEW: forward from situational_params
)
```

**NBA parity:** `make_nba_quant_agent` in `src/sportsbet/prop/nba_agents.py` has the same missing bridge. The same `situational_params` pattern must be applied there so NBA gamelog conditional queries also fire. The `NBAQueryBuilder` `_is_conditional()` check and gamelog templates are already implemented.

### Anti-Patterns to Avoid

- **Do not add a new GraphState field.** `situational_params` is already declared in `state.py` (line 146). No schema changes.
- **Do not restructure the closure factory signature.** `make_prop_quant_agent(pool)` and `make_nba_quant_agent(pool)` take only `pool`. The `situational_params` bridge is read from state at invocation time, not injected at construction time.
- **Do not use `state["situational_params"]` with hard key access.** Use `state.get("situational_params")` — the field is Optional and may be absent from states that predated Phase 18.
- **Do not change PropQueryBuilder or NBAQueryBuilder.** The conditional WHERE clause machinery is already correct and passing tests. The bug is upstream (the agent never populates the field).
- **Do not change PropParams model.** `teammate_out: Optional[list[str]] = None` is already defined.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reading dict values safely | Custom accessor class | `state.get("situational_params") or {}` | Standard Python dict.get with falsy fallback is the established pattern in all existing agents |
| Conditional field population | New Pydantic validator | Pass `teammate_out=teammate_out` as constructor kwarg | PropParams.teammate_out = None is already backward compatible |
| Test mocking of write_player_prop_snapshot | New test fixture class | `unittest.mock.patch("sportsbet.graph.agents.write_player_prop_snapshot")` | Module-level import pattern locks mock target — established by Phase 14 decision |

---

## Common Pitfalls

### Pitfall 1: NBA Agent Bridge Omission
**What goes wrong:** INT-1 fix applied only to `prop/agents.py` (NFL) but not to `prop/nba_agents.py` (NBA). NBA gamelog conditional queries remain dead code.
**Why it happens:** The audit description focuses on `make_prop_quant_agent`; `make_nba_quant_agent` is a parallel closure with identical structure and identical missing bridge.
**How to avoid:** Apply `situational_params` read + `teammate_out` propagation to both `prop/agents.py` and `prop/nba_agents.py` in the same task.
**Warning signs:** NBA gamelog tests pass when `PropParams.teammate_out` is supplied directly, but end-to-end `make_nba_quant_agent` invocation with `situational_params` in state does not trigger the gamelog template.

### Pitfall 2: `state.get()` vs `state[]` on Optional Fields
**What goes wrong:** Using `state["situational_params"]` raises `KeyError` when the state dict was created before Phase 18 (e.g., older checkpoint replays).
**Why it happens:** `situational_params` is Optional and has no `Required` annotation; states from pre-Phase 18 runs lack the key.
**How to avoid:** Always `state.get("situational_params")` — matches all other Optional field reads in both agent files (e.g., `state.get("prop_type", "pass_yds")`).

### Pitfall 3: Empty Dict vs None for situational
**What goes wrong:** `situational_params = {}` (empty dict, not None) causes `{}.get("teammate_out_signals")` to return `None` correctly, but `situational_params or {}` is needed because the state value may literally be `None` (the explicit return from `_extract_situational_params` when no Out players exist).
**How to avoid:** Use `state.get("situational_params") or {}` — the `or {}` handles both `None` and absent key.

### Pitfall 4: Test Scope for INT-2
**What goes wrong:** The test patches `write_player_prop_snapshot` but the assertion checks the `sport` keyword argument, not just call count. The mock call args must be inspected with `mock_call.kwargs["sport"]` or by inspecting `PlayerPropSnapshotCreate` instantiation.
**How to avoid:** Inspect the `call_args` on the patched `write_player_prop_snapshot` or patch `PlayerPropSnapshotCreate` directly and assert `sport=sport_variable` on the captured call.

### Pitfall 5: `or None` on teammate_out extraction
**What goes wrong:** `situational.get("teammate_out_signals")` returns `[]` (empty list) if the injury scraper produced an empty signals list. An empty list passed to `PropParams.teammate_out` is falsy but valid; the query builder checks `if params.teammate_out:` which correctly skips it for empty lists. However, passing `[]` is semantically equivalent to `None` here — use `or None` to normalize.
**How to avoid:** `teammate_out = situational.get("teammate_out_signals") or None`

---

## Code Examples

Verified patterns from existing codebase:

### Reading Optional state fields (established pattern in all agents)
```python
# Source: src/sportsbet/prop/agents.py lines 136-141 (existing)
player_id: str = state.get("receiver_gsis_id", "")
season: int = state["season"]
prop_type: str = state.get("prop_type", "pass_yds")
prop_filters: dict[str, object] = state.get("prop_filters", {})
```

### INT-1 bridge pattern (new addition, same style)
```python
# After existing state reads, before PropParams construction:
situational: dict = state.get("situational_params") or {}
teammate_out: list[str] | None = situational.get("teammate_out_signals") or None
```

### PropParams construction with teammate_out
```python
# Source: src/sportsbet/graph/models.py lines 195-200 (teammate_out field definition)
params = PropParams(
    game_id=game_id,
    player_id=player_id,
    season=season,
    sport="nfl",
    prop_type=prop_type,
    line=line,
    filters=prop_filters if prop_filters else {},
    teammate_out=teammate_out,   # None when no injuries; list[str] when Out players
)
```

### INT-2 fix (PlayerPropSnapshotCreate sport kwarg)
```python
# Source: src/sportsbet/graph/agents.py line 219 (sport already resolved)
sport = state.get("sport") or "nfl"

# Fix at line 304:
snap = PlayerPropSnapshotCreate(
    sport=sport,   # was: sport="nfl"
    game_id=event_data.get("id"),
    player_name=outcome.get("name", "Unknown"),
    sportsbook=bookmaker.get("key", "unknown"),
    prop_type=market.get("key", "unknown"),
    line=_Dec(str(point)) if point is not None else None,
    price=int(price),
    implied_probability=implied_prob,
)
```

### Test pattern for INT-2 (existing similar test in test_context_and_vig_completion.py)
```python
# Source: tests/test_context_and_vig_completion.py (GAP-INT-1 test pattern, lines 271-310)
# Patches module-level imports; asserts call_args
@pytest.mark.asyncio
async def test_prop_snapshot_uses_sport_variable_nba() -> None:
    with patch("sportsbet.graph.agents.write_player_prop_snapshot") as mock_write, \
         patch("sportsbet.graph.agents.OddsAPIPoller") as mock_poller, ...:
        # invoke context_agent with state["sport"] = "nba"
        # assert mock_write.call_args[1]["snap"].sport == "nba"
        ...
```

### Test pattern for INT-1 (new test)
```python
@pytest.mark.asyncio
async def test_prop_quant_agent_forwards_teammate_out_to_prop_params() -> None:
    """make_prop_quant_agent reads situational_params from state and passes
    teammate_out_signals to PropParams.teammate_out before building query."""
    pool = MagicMock()
    captured_params: list[PropParams] = []

    async def fake_run_prop_query(p, params):
        captured_params.append(params)
        return PropResult(data_source="test", true_probability=Decimal("0.6"), ...)

    with patch("sportsbet.prop.agents.run_prop_query", side_effect=fake_run_prop_query):
        agent = make_prop_quant_agent(pool)
        state = {
            "session_id": "s1", "game_id": "g1", "season": 2023,
            "receiver_gsis_id": "00-0036355",
            "prop_type": "rec_yds", "prop_line": 75.5,
            "prop_filters": {}, "kinematic_result": None,
            "situational_params": {"teammate_out_signals": ["Davante Adams"]},
        }
        await agent(state)

    assert captured_params[0].teammate_out == ["Davante Adams"]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| sport="nfl" literal in PlayerPropSnapshotCreate | sport=sport variable | Phase 19 (this phase) | NBA prop snapshots stored with correct sport tag, enabling downstream NBA prop queries to find their rows |
| PropParams.teammate_out always None in automated runs | Read from situational_params → PropParams.teammate_out | Phase 19 (this phase) | Phase 18 conditional gamelog WHERE clauses actually fire in the pipeline |

**No deprecated approaches involved.** These are fixes to code that was implemented but incorrectly wired.

---

## Open Questions

1. **Should NBA gamelog queries for SC-4 also receive `teammate_out` via the same bridge?**
   - What we know: `NBAQueryBuilder.build()` checks `params.teammate_out` and dispatches to gamelog template when set. `make_nba_quant_agent` has the same structure gap as `make_prop_quant_agent`.
   - What's unclear: The audit explicitly says INT-1 fix is `src/sportsbet/prop/agents.py` — but `nba_agents.py` is the parallel file for NBA.
   - Recommendation: Apply the bridge to both files. The NBA gamelog conditional path was the primary motivation for Phase 18 SC-4 and SC-5. Fixing only NFL leaves a symmetrical gap.

2. **Should `last_n_games`, `opponent_team`, `home_away` also be forwarded from `prop_filters`?**
   - What we know: These fields are already part of `PropParams` (Phase 18). They can be injected via the existing `prop_filters` dict mechanism (state key `prop_filters`). The `situational_params` key specifically carries `teammate_out_signals` from the injury scraper.
   - What's unclear: Are callers expected to pass `last_n_games` via `prop_filters` or via a separate mechanism?
   - Recommendation: For Phase 19, scope the INT-1 fix narrowly to `teammate_out_signals → PropParams.teammate_out`. The other situational fields (`last_n_games`, `opponent_team`, `home_away`) are already passable via `prop_filters` and do not have a dedicated state key. This matches the audit description exactly.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.x + pytest-asyncio |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_prop_integration_fixes.py -x -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-01 | PlayerPropSnapshotCreate uses dynamic sport variable for NBA state | unit | `python -m pytest tests/test_prop_integration_fixes.py::test_prop_snapshot_uses_sport_variable_nba -x` | Wave 0 |
| PROP-01 | PlayerPropSnapshotCreate uses "nfl" when no sport in state (regression) | unit | `python -m pytest tests/test_prop_integration_fixes.py::test_prop_snapshot_sport_defaults_to_nfl -x` | Wave 0 |
| PROP-01 (INT-1) | make_prop_quant_agent forwards teammate_out_signals to PropParams.teammate_out | unit | `python -m pytest tests/test_prop_integration_fixes.py::test_prop_quant_agent_forwards_teammate_out -x` | Wave 0 |
| PROP-01 (INT-1) | make_nba_quant_agent forwards teammate_out_signals to PropParams.teammate_out | unit | `python -m pytest tests/test_prop_integration_fixes.py::test_nba_quant_agent_forwards_teammate_out -x` | Wave 0 |
| PROP-01 (INT-1) | No situational_params in state → PropParams.teammate_out is None (regression) | unit | `python -m pytest tests/test_prop_integration_fixes.py::test_prop_quant_agent_teammate_out_none_when_no_situational -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_prop_integration_fixes.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green (currently 188 passed, 11 skipped, 2 xfailed) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_prop_integration_fixes.py` — covers all 5 test cases above (new file, does not exist yet)

---

## Sources

### Primary (HIGH confidence)
- `src/sportsbet/graph/agents.py` lines 219, 304 — exact bug location confirmed by direct file read
- `src/sportsbet/prop/agents.py` lines 129-191 — full `make_prop_quant_agent` closure read; missing state reads confirmed
- `src/sportsbet/prop/nba_agents.py` lines 134-215 — `make_nba_quant_agent` closure; same gap confirmed
- `src/sportsbet/graph/models.py` lines 155-200 — `PropParams.teammate_out` field definition confirmed present
- `src/sportsbet/graph/state.py` line 146 — `situational_params` GraphState field confirmed present
- `.planning/v1.0-MILESTONE-AUDIT.md` — INT-1 and INT-2 exact locations and descriptions

### Secondary (MEDIUM confidence)
- `src/sportsbet/prop/query_builder.py` lines 192-215 — `PropQueryBuilder` teammate_out WHERE clause verified present and correct
- `src/sportsbet/prop/nba_query_builder.py` lines 183-270 — `NBAQueryBuilder` conditional dispatch verified present
- `tests/` — pytest run confirms 188 passed baseline before this phase

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed, no new dependencies
- Architecture: HIGH — exact file locations, line numbers, and variable names confirmed by direct source read
- Pitfalls: HIGH — derived from existing locked decisions and direct code inspection

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (stable domain — no external API dependencies; pure internal wiring fixes)
