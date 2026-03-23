# Phase 14: Prop Integration Gap Closure - Research

**Researched:** 2026-03-23
**Domain:** LangGraph graph wiring, prop persistence, TypedDict contract, NBA sport key routing
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-01 | System ingests live NFL and NBA player prop odds from The Odds API and writes timestamped `PlayerPropSnapshot` rows to PostgreSQL | `write_player_prop_snapshot()` and `PlayerPropSnapshotCreate` are implemented in `src/sportsbet/ingestion/prop_odds.py`; `fetch_player_props()` is implemented in `odds_poller.py`. The only missing piece is a call site in `make_context_agent` that chains fetch → write. All persistence machinery is complete and tested individually. |
| PROP-06 | `PropArbitrageAgent` flags mispriced player props; NBA path returns non-None `EVSignal` | `make_prop_arbitrage_agent(sport="nfl")` is hardcoded at line 397 of `graph.py`. The `_state_key` is therefore `"prop_result"` for ALL invocations. NBA quant writes `nba_prop_result`; the guard fires because `state["prop_result"]` is None. Fix: change the `sport` param in `create_graph_with_sqlite()` to `"nba"`, or refactor the agent to be sport-agnostic. |
| NBA-02 | System applies pace/back-to-back/def-rating adjustments to NBA prop distributions | `_apply_nba_context_adjustments()` is fully implemented and tested. The failure is entirely downstream: the NBA EVSignal is never produced because of the PROP-06 sport key mismatch. Fixing PROP-06 automatically unblocks NBA-02 in production. |
</phase_requirements>

---

## Summary

Phase 14 is a pure integration fix phase. No new algorithms, models, or tables need to be created. All three gaps are wiring or contract omissions that were left behind during Phase 13 implementation.

**Gap 1 (PROP-01):** `OddsAPIPoller.fetch_player_props()` and `write_player_prop_snapshot()` are both complete, tested, and individually correct. They were never connected. The connection point is `make_context_agent` in `src/sportsbet/graph/agents.py`, specifically the block after Step 1b that already persists game-level odds — an analogous step for prop odds needs to be added. The wiring must handle each raw per-event prop response and convert it into a `PlayerPropSnapshotCreate` object before calling `write_player_prop_snapshot()`.

**Gap 2 (PROP-06 / NBA-02):** `create_graph_with_sqlite()` calls `make_prop_arbitrage_agent(sport="nfl")` on line 397 of `graph.py`. This makes the single shared `prop_arbitrage_node` read `state["prop_result"]` for ALL routes — including the NBA path. The NBA quant agent writes `state["nba_prop_result"]`. The cleanest fix with minimal surface area is to change `sport="nfl"` to remove the `sport` param entirely from `make_prop_arbitrage_agent` and instead have it inspect both state keys. Alternatively, the production factory could construct two separate arbitrage nodes (one per sport) and routing could be adjusted. The audit recommends the sport-agnostic approach as simplest.

**Gap 3 (INFRA-01 / prop_filters):** `prop/agents.py` line 141 and `nba_agents.py` line 170 both access `state.get("prop_filters", {})`. `prop_filters` is absent from `GraphState` TypedDict. This violates INFRA-01 and makes `state.get()` a runtime-only workaround — TypedDict's static analysis cannot flag misuse. The fix is a single-line addition to `state.py`.

**Primary recommendation:** One plan, three targeted code changes — all in files already understood from prior phases. No new dependencies, no migrations, no new agent logic.

---

## Standard Stack

### Core (all already installed — no new dependencies)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `asyncpg` | >=0.29 | Async pool for agent queries | Already in use |
| `sqlalchemy` | >=2.0 | Sync engine for `write_player_prop_snapshot` | Already in use |
| `pydantic` | >=2.7,<3.0 | `PlayerPropSnapshotCreate` validation | Already in use |
| `structlog` | >=24.1 | Structured logging in agent closures | Already in use |
| `langgraph` | installed | Graph state and node wiring | Already in use |

No new packages required for this phase.

---

## Architecture Patterns

### Pattern 1: Closure-scoped persistence (mirrors Phase 8 odds persistence pattern)

**What:** `make_context_agent` already contains a Step 1b block that lazily initializes a sync engine and calls `write_odds_snapshot()` after fetching game-level odds. The prop persistence follows an identical pattern.

**When to use:** Any time an agent must persist data without a pool (only sync engine available for write path).

**Example (existing Step 1b from agents.py — the prop write mirrors this exactly):**
```python
# Existing game-level odds persistence in make_context_agent (lines 193–216 of agents.py)
if odds_snapshot is not None:
    try:
        if not _sync_engine_cache:
            import sqlalchemy as _sa
            from sportsbet.config import settings as _settings
            _engine = _sa.create_engine(
                _settings.database_url,
                echo=False,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5},
            )
            _sync_engine_cache.append(_engine)
        snap_create = OddsSnapshotCreate(...)
        write_odds_snapshot(snap_create, engine=_sync_engine_cache[0])
    except Exception as exc:
        log.warning("context_agent_odds_persist_error", error=str(exc))
```

**For prop persistence, the analogous pattern:**
```python
# After fetch_player_props() returns a list[dict] of per-event prop responses:
for event_data in raw_props:
    for bookmaker in event_data.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            for outcome in market.get("outcomes", []):
                price = outcome.get("price")
                if price is None:
                    continue
                raw_prob = american_to_raw_prob(price)
                implied_prob = Decimal(str(round(float(raw_prob), 6)))
                snap = PlayerPropSnapshotCreate(
                    sport=sport,           # "nfl" or "nba"
                    game_id=event_data.get("id"),
                    player_name=outcome.get("name", "Unknown"),
                    sportsbook=bookmaker.get("key", "unknown"),
                    prop_type=market.get("key", "unknown"),
                    line=Decimal(str(outcome.get("point", 0))) if outcome.get("point") is not None else None,
                    price=int(price),
                    implied_probability=implied_prob,
                )
                write_player_prop_snapshot(snap, engine=_sync_engine_cache[0])
```

**Important:** `american_to_raw_prob` is already imported in `agents.py` indirectly via `_extract_odds_snapshot`. It lives at `sportsbet.quant.vig`. Import it at the top of the closure using the lazy-import pattern established in Phase 4.

### Pattern 2: Sport-agnostic prop arbitrage (fix for PROP-06)

**What:** Remove `sport` param dependency from `create_graph_with_sqlite()` by making `make_prop_arbitrage_agent` check both state keys and use the non-None one.

**Option A (recommended — minimal surface area):** Modify `make_prop_arbitrage_agent` to accept `sport=None` as a special value meaning "auto-detect from state". When `sport is None`, try `state.get("prop_result")` first, then `state.get("nba_prop_result")`. Log which key was used.

```python
# In make_prop_arbitrage_agent — sport-agnostic fallback
if sport is None:
    prop_result = state.get("prop_result") or state.get("nba_prop_result")
    _resolved_sport = "nba" if state.get("nba_prop_result") is not None else "nfl"
else:
    _state_key = "nba_prop_result" if sport == "nba" else "prop_result"
    prop_result = state.get(_state_key)
```

**Option B (simpler, no signature change):** Change the call in `create_graph_with_sqlite()` from `sport="nfl"` to constructing two separate prop arbitrage nodes — one per sport — and adding both to the graph. NBA quant routes to the NBA arbitrage node, NFL quant routes to the NFL node. This requires more graph surgery (new node names, new edges).

**Recommendation: Option A** — one-line change in `create_graph_with_sqlite()` (pass `sport=None`) and minimal logic change in `make_prop_arbitrage_agent`. No graph topology changes.

### Pattern 3: TypedDict field addition (prop_filters)

**What:** Add `prop_filters: dict[str, Any]` to `GraphState` TypedDict. Follows the exact same pattern used when `prop_type`, `prop_line`, `nba_context_signals`, and `nba_prop_result` were added in Phases 12–13.

**When to use:** Any state field accessed via `state.get()` in agent code that is not yet declared in `GraphState`.

**Example:**
```python
# In state.py, add after prop_line:
prop_filters: dict[str, Any]  # type: ignore[misc]  # Optional prop filter context (phase 14 — INFRA-01)
```

**Runtime note:** Since agents currently use `state.get("prop_filters", {})`, the field needs a safe default. TypedDict fields do not have defaults in Python — callers must supply `prop_filters: {}` in their initial state dict. The existing test fixtures in `test_prop_pipeline_wiring.py` do NOT include `prop_filters`. They will need to be updated.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Convert American odds to implied prob for prop write | Custom conversion | `american_to_raw_prob` from `sportsbet.quant.vig` | Already tested, handles edge cases, Decimal-safe |
| DB write validation | Direct ORM insert | `PlayerPropSnapshotCreate` Pydantic model + `write_player_prop_snapshot()` | Already implemented in `prop_odds.py`, tested |
| Sport state key selection | New routing logic | Modify `make_prop_arbitrage_agent` sport-agnostic branch | Smallest change, no new nodes |

---

## Common Pitfalls

### Pitfall 1: Module-level imports for mock patchability

**What goes wrong:** If `write_player_prop_snapshot` and `PlayerPropSnapshotCreate` are imported only inside the closure body of `make_context_agent`, they cannot be patched via `unittest.mock.patch("sportsbet.graph.agents.write_player_prop_snapshot")`.

**Why it happens:** Python's mock.patch replaces the name in the module namespace. If the import happens inside a function call, the name doesn't exist at patch time.

**How to avoid:** Import `write_player_prop_snapshot` and `PlayerPropSnapshotCreate` at the top of `agents.py` at module level (not inside the closure), exactly as `write_odds_snapshot` and `OddsSnapshotCreate` are already imported.

**Evidence:** Line 38 of `agents.py` — `from sportsbet.ingestion.odds import OddsSnapshotCreate, write_odds_snapshot` — this is the exact pattern to follow.

**Warning signs:** Test assertion `mock_write.assert_called_once()` silently passes without actually calling mock if import is inside closure.

### Pitfall 2: prop_filters TypedDict field requires initial state update in ALL existing fixtures

**What goes wrong:** Adding `prop_filters: dict[str, Any]` as a required TypedDict field means every test that passes an initial state dict without `prop_filters` will raise a `TypedDict` contract violation at runtime (or mypy will flag it).

**Why it happens:** `TypedDict` fields without `total=False` or `Optional` are required by the type system.

**How to avoid:** Either add `prop_filters` to every test fixture that builds a `GraphState` dict, OR declare it as `Optional` with a default in state. Since TypedDict does not support defaults directly, the cleanest solution is to make the field `Optional[dict[str, Any]]` and update agent code to use `state.get("prop_filters") or {}`.

**Warning signs:** Test failures with `KeyError: prop_filters` in LangGraph state validation.

**Recommendation:** Declare as `dict[str, Any] | None` in TypedDict, and agents already use `state.get("prop_filters", {})` which handles None gracefully.

### Pitfall 3: NBA prop persistence requires sport="nba" in OddsAPIPoller context

**What goes wrong:** `make_context_agent` currently only calls `fetch_nfl_odds()`. It never calls `fetch_player_props("nba")` or `fetch_player_props("nfl")`. The Phase 14 wiring adds prop persistence but `make_context_agent` is an NFL-scoped agent — it may not be the right location for NBA prop ingestion.

**Why it happens:** Phase 15 plans to extend context agent with NBA game odds. Phase 14's PROP-01 scope is just wiring the persistence — not NBA-specific ingestion.

**How to avoid:** For Phase 14, wire `fetch_player_props("nfl")` in `make_context_agent` (which is already NFL-scoped). NBA prop ingestion is Phase 15 territory. Document this explicitly in the plan.

**Evidence from audit:** "Wire `fetch_player_props → write_player_prop_snapshot` inside `make_context_agent` or a dedicated prop ingestion step." — The audit suggests `make_context_agent` as the call site.

### Pitfall 4: `_NO_SIGNAL` mutable dict shared across invocations

**What goes wrong:** `_NO_SIGNAL: dict[str, Any] = {"ev_signal": None}` at module level in `arbitrage.py` — this is a shared mutable dict. If `make_prop_arbitrage_agent` returns `_NO_SIGNAL` by reference and LangGraph mutates it, all future calls that return `_NO_SIGNAL` return a polluted dict.

**Why it happens:** Python dict is mutable; module-level shared state across closures.

**How to avoid:** This is an existing pre-Phase-14 issue. Do not mutate it in Phase 14 changes. The `prop_arbitrage_agent` only reads `_NO_SIGNAL` (returns it), never mutates it — so it is safe as-is. Do not change it.

### Pitfall 5: write_player_prop_snapshot uses sync engine — must not be called inside async hot path without thread pool

**What goes wrong:** `write_player_prop_snapshot` uses a synchronous SQLAlchemy engine (`engine.begin()`). Calling it directly inside an `async def` function blocks the event loop.

**Why it happens:** `make_context_agent` is an async closure. Blocking SQLAlchemy calls inside async functions stall the LangGraph event loop.

**How to avoid:** The existing `write_odds_snapshot` call in `make_context_agent` already uses the sync engine inside the async context agent — this is an existing pattern in the codebase (Phase 8 decision). The project accepts this tradeoff in v1 (low concurrency, local dev). Phase 14 should follow the same pattern. Document that this is acceptable for v1 and flag for Phase 2 async refactor if needed.

---

## Code Examples

### Fix 1: Import additions at top of agents.py

```python
# Source: agents.py existing pattern (line 38)
# Add alongside existing odds import:
from sportsbet.ingestion.odds import OddsSnapshotCreate, write_odds_snapshot
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, write_player_prop_snapshot
```

### Fix 2: Prop persistence block inside make_context_agent

```python
# Source: mirrors Step 1b in make_context_agent (lines 193–216)
# Add as Step 1c after the existing odds persistence block:

# --- Step 1c: Fetch and persist player prop snapshots (PROP-01) ---
try:
    async with OddsAPIPoller(api_key=api_key, daily_credit_cap=daily_credit_cap) as poller:
        raw_props = await poller.fetch_player_props("nfl")
    if not _sync_engine_cache:
        import sqlalchemy as _sa
        from sportsbet.config import settings as _settings
        _engine = _sa.create_engine(
            _settings.database_url, echo=False, pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )
        _sync_engine_cache.append(_engine)
    from sportsbet.quant.vig import american_to_raw_prob
    from decimal import Decimal as _Decimal
    for event_data in raw_props:
        for bookmaker in event_data.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    price = outcome.get("price")
                    if price is None:
                        continue
                    try:
                        raw_prob = american_to_raw_prob(int(price))
                        implied_prob = _Decimal(str(round(float(raw_prob), 6)))
                        point = outcome.get("point")
                        snap = PlayerPropSnapshotCreate(
                            sport="nfl",
                            game_id=event_data.get("id"),
                            player_name=outcome.get("name", "Unknown"),
                            sportsbook=bookmaker.get("key", "unknown"),
                            prop_type=market.get("key", "unknown"),
                            line=_Decimal(str(point)) if point is not None else None,
                            price=int(price),
                            implied_probability=implied_prob,
                        )
                        write_player_prop_snapshot(snap, engine=_sync_engine_cache[0])
                    except Exception as snap_exc:
                        log.warning("prop_snapshot_write_error", error=str(snap_exc))
    log.info("context_agent_props_persisted", game_id=game_id)
except BudgetExhaustedError as exc:
    log.warning("context_agent_prop_budget_exhausted", error=str(exc))
except Exception as exc:
    log.warning("context_agent_prop_fetch_error", error=str(exc))
```

### Fix 3: Sport-agnostic prop arbitrage agent

```python
# Source: src/sportsbet/prop/arbitrage.py — modify make_prop_arbitrage_agent

def make_prop_arbitrage_agent(
    settings_override: Any = None,
    sport: str | None = "nfl",  # None = auto-detect from state
) -> Any:
    cfg = settings_override if settings_override is not None else _settings

    async def prop_arbitrage_agent(state: GraphState) -> dict:
        # Resolve prop_result from state based on sport param
        if sport is None:
            # Auto-detect: prefer nba_prop_result if set, else prop_result
            prop_result = state.get("nba_prop_result") or state.get("prop_result")
            resolved_sport = "nba" if state.get("nba_prop_result") is not None else "nfl"
        else:
            _state_key = "nba_prop_result" if sport == "nba" else "prop_result"
            prop_result = state.get(_state_key)
            resolved_sport = sport

        log.info("prop_arbitrage_agent.enter", sport=resolved_sport)
        # ... rest of existing logic unchanged
```

```python
# Source: src/sportsbet/graph/graph.py — create_graph_with_sqlite() line 397
# Change:
prop_arbitrage_node = make_prop_arbitrage_agent(sport="nfl")
# To:
prop_arbitrage_node = make_prop_arbitrage_agent(sport=None)  # auto-detect NFL/NBA from state
```

### Fix 4: GraphState TypedDict addition

```python
# Source: src/sportsbet/graph/state.py — add after prop_line field
# Change from undeclared (state.get() workaround) to explicit:
prop_filters: dict[str, Any] | None  # type: ignore[misc]  # Prop filter context; None for non-prop routes (Phase 14 — INFRA-01)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sport="nfl"` hardcoded in production factory | `sport=None` auto-detects from state | Phase 14 | Enables NBA prop EVSignal in production |
| `write_player_prop_snapshot` never called | Called from `make_context_agent` Step 1c | Phase 14 | `player_prop_snapshots` table populated on context agent run |
| `prop_filters` accessed via `state.get()` only | `prop_filters` declared in `GraphState` TypedDict | Phase 14 | TypedDict contract integrity restored; mypy can verify usages |

**No deprecated patterns in this phase** — all changes are additive wiring fixes to existing code.

---

## Open Questions

1. **Should prop persistence be NFL-only or both sports?**
   - What we know: `make_context_agent` is currently NFL-scoped (`fetch_nfl_odds()` only). Phase 15 adds NBA context ingestion.
   - What's unclear: Should `fetch_player_props("nba")` also be called in Phase 14, or only `"nfl"`?
   - Recommendation: Scope Phase 14 to NFL prop persistence only (`fetch_player_props("nfl")`). NBA prop persistence follows naturally when Phase 15 adds NBA context agent routing. This minimizes risk.

2. **Does `prop_filters: dict[str, Any] | None` break existing tests?**
   - What we know: The field is NOT currently in `GraphState`. All existing test fixtures that build a full state dict will be missing it.
   - What's unclear: Does LangGraph's `StateGraph(GraphState)` enforce TypedDict completeness at runtime?
   - Recommendation: Add the field as `Optional` (i.e., `dict[str, Any] | None`). Existing state dicts that omit it will pass at runtime (Python TypedDict is not enforced at runtime). `state.get("prop_filters", {})` already handles `None` correctly.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest with `asyncio_mode = "auto"` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_prop_odds.py tests/test_prop_pipeline_wiring.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-01 | After context agent run, `player_prop_snapshots` has at least one row with non-null `implied_probability` | unit (mocked engine) | `pytest tests/test_prop_odds.py::test_write_player_prop_snapshot -x` | existing but tests writer only; no test for context agent calling writer |
| PROP-01 (wiring) | `make_context_agent` calls `write_player_prop_snapshot` when props fetched | unit (mock patch) | `pytest tests/test_prop_odds.py -x` | needs new test |
| PROP-06 | NBA prop pipeline returns non-None EVSignal | integration | `pytest tests/test_prop_pipeline_wiring.py::TestE2EPropPipelineWiring::test_e2e_nba_prop_pipeline -x` | existing test already covers NBA e2e |
| NBA-02 | NBA quant results consumed by arbitrage in production factory | integration (via PROP-06 fix) | `pytest tests/test_prop_pipeline_wiring.py -x` | existing |
| INFRA-01 | `GraphState` declares `prop_filters` | unit | `pytest tests/test_prop_pipeline_wiring.py -x` | existing fixtures need `prop_filters` key added |

### Sampling Rate

- **Per task commit:** `pytest tests/test_prop_odds.py tests/test_prop_pipeline_wiring.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_prop_integration_gap_closure.py` — new test file covering:
  - PROP-01 wiring: `make_context_agent` calls `write_player_prop_snapshot` at least once after `fetch_player_props` returns data (mock `write_player_prop_snapshot` at module level)
  - PROP-06 fix: production factory `sport=None` means NBA state key resolves correctly
  - INFRA-01: `GraphState` TypedDict contains `prop_filters` field

- [ ] Update `tests/test_prop_pipeline_wiring.py` `_make_base_state()` to include `prop_filters: {}` — required once `prop_filters` is declared in `GraphState`

*(Existing test infrastructure: pytest with asyncio_mode=auto, pythonpath=['src', 'site-packages']. No new framework install needed.)*

---

## Sources

### Primary (HIGH confidence)

- `src/sportsbet/graph/graph.py` — lines 387–421, `create_graph_with_sqlite()` — exact line of the PROP-06 bug (line 397: `sport="nfl"` hardcoded)
- `src/sportsbet/graph/agents.py` — lines 162–252, `make_context_agent` — existing Step 1b (game odds persistence) provides the exact pattern for Step 1c (prop persistence)
- `src/sportsbet/graph/state.py` — complete `GraphState` TypedDict — confirms `prop_filters` is absent
- `src/sportsbet/ingestion/prop_odds.py` — `write_player_prop_snapshot` and `PlayerPropSnapshotCreate` — fully implemented, no changes needed
- `src/sportsbet/ingestion/odds_poller.py` — `OddsAPIPoller.fetch_player_props` — fully implemented
- `src/sportsbet/prop/arbitrage.py` — `make_prop_arbitrage_agent` — `_state_key` at line 120 is the root cause
- `.planning/v1.0-MILESTONE-AUDIT.md` — authoritative description of all three gaps with file/line references

### Secondary (MEDIUM confidence)

- `tests/test_prop_pipeline_wiring.py` — confirms existing NBA e2e test passes with `sport="nba"` when prop arbitrage node is explicitly constructed with the right sport
- `tests/test_prop_odds.py` — confirms `write_player_prop_snapshot` test passes with mocked engine

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all existing dependencies, no new installs
- Architecture: HIGH — all three fixes are direct code changes in files fully read and verified
- Pitfalls: HIGH — verified from code analysis and existing test patterns
- Test gaps: HIGH — gaps identified by reading actual test files and comparing against success criteria

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable codebase, no fast-moving dependencies)
