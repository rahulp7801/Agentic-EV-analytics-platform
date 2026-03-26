# Phase 23: Fix PropArbitrageAgent EV — Player Prop Implied Probability - Research

**Researched:** 2026-03-26
**Domain:** Python / LangGraph agent surgery — Pydantic v2 models, asyncpg, Decimal arithmetic
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-06 | `PropArbitrageAgent` flags mispriced player props by comparing `PropResult.true_probability` against sportsbook implied probability from `player_prop_snapshots`, outputting raw EV percentage and 3-bullet Trade Plan thesis with fractional Kelly sizing — no flat bet sizes | Research identifies exact code path to change: replace `context_signals.odds_snapshot` lookup with a `player_prop_snapshots`-matched lookup; all downstream EV/Kelly math is unchanged |
</phase_requirements>

---

## Summary

`PropArbitrageAgent` (in `src/sportsbet/prop/arbitrage.py`) currently reads implied probability from `context_signals.odds_snapshot` — an `AgentOddsSnapshot` that was built from the game-level h2h / moneyline market fetched by the Context Agent. `PropResult.true_probability` is the model probability that a *specific player prop outcome* occurs (e.g., "Patrick Mahomes passes over 250.5 yards"). Dividing these two probabilities produces a mathematically incommensurable comparison: the numerator is a prop-market probability, the denominator is a game-winner moneyline implied probability. The resulting EV percentage is numerically meaningless.

The fix is surgical: before computing EV, the agent must look up the matching `PlayerPropSnapshot` row from `state["player_prop_snapshots"]` using the player / prop_type / line keys already present in state (`state["prop_type"]`, `state["prop_line"]`, and the player name accessible via `state["context_signals"]` or a new `player_name` state field). The matched snapshot carries `implied_probability` (a pre-computed `Decimal` stored at ingestion time) and optionally a `price` (American odds integer). The existing `american_to_raw_prob` + devig path from `quant/vig.py` is already tested and available if re-devigging from raw American odds is preferred over using the stored `implied_probability` directly.

`PlayerPropSnapshot` rows are already being written to PostgreSQL by the Context Agent (Step 1c of `make_context_agent`). The gap is that those rows are never read back into `GraphState` and never passed to `PropArbitrageAgent`. The fix requires: (1) adding a `player_prop_snapshots` field to `GraphState`, (2) populating it in the Context Agent (or in a separate load step), and (3) modifying `prop/arbitrage.py` to match on player/prop_type/line and extract `implied_probability` from the matched snapshot instead of from `context_signals.odds_snapshot`.

**Primary recommendation:** Add `player_prop_snapshots: list[PlayerPropSnapshotCreate] | None` to GraphState. Populate it from the Context Agent's existing raw_props fetch. In `PropArbitrageAgent`, iterate that list to find the matching snapshot; if none found, return `_NO_SIGNAL` with a structured log. All EV and Kelly math downstream remains identical.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python Decimal | stdlib | All probability and fraction arithmetic | Locked Phase 2 decision — float forbidden on any probability field |
| Pydantic v2 | `>=2.0` | Input/output model validation with `ConfigDict(strict=True)` | Locked CLAUDE.md requirement — all agent I/O must be Pydantic |
| structlog | installed | Structured logging at every guard return | Locked pattern from all existing agents |
| asyncpg | `>=0.29` | Async DB pool (for any future DB-backed snapshot lookup) | Phase 1 locked decision — hot-path agent queries use asyncpg pool |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sportsbet.quant.vig.american_to_raw_prob` | local | Convert American odds int to raw implied prob | If choosing to re-derive implied_prob from stored `price` rather than stored `implied_probability` |
| `sportsbet.quant.vig.remove_vig_multiplicative` / `remove_vig_power` | local | Devig pair of sides for a prop market | Only needed if two-sided prop snapshot rows are available to devig together — for single-side use stored `implied_probability` directly |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Passing snapshots through GraphState | DB query inside PropArbitrageAgent | DB query inside agent violates Phase 5 locked decision ("make_arbitrage_agent takes optional settings_override (not pool) — arbitrage math is stateless; no DB access needed"); same rule should apply to PropArbitrageAgent |
| Using stored `implied_probability` directly | Re-deriving from `price` via vig.py | Stored value is already devigged at ingestion (single-side, vig-inclusive); for consistency with QUANT-02, use stored value directly — re-devigging a single-side price without its opposing side is not well-defined multiplicatively |

---

## Architecture Patterns

### Recommended Project Structure

No new files required. Changes are confined to:

```
src/sportsbet/
├── graph/
│   └── state.py          # Add player_prop_snapshots field to GraphState
│   └── agents.py         # Populate player_prop_snapshots in make_context_agent return dict
├── prop/
│   └── arbitrage.py      # Replace context_signals.odds_snapshot with snapshot match logic
tests/
└── test_prop_arbitrage.py  # Update/add tests for new implied_prob source
```

### Pattern 1: GraphState field addition
**What:** Add `player_prop_snapshots: list[PlayerPropSnapshotCreate] | None` to `GraphState`. Follows the exact pattern used for `nba_context_signals`, `prop_filters`, `situational_params` — all added as `Optional` with `None` default, accessed via `state.get()`.

**When to use:** Every time a new data artifact must flow from an upstream node to a downstream node.

**Example (from existing Phase 14 decision pattern):**
```python
# In state.py TypedDict — add after situational_params
player_prop_snapshots: list[Any] | None  # type: ignore[misc]
# PlayerPropSnapshotCreate list populated by context_agent (Phase 23 — PROP-06)
```

### Pattern 2: Context Agent return dict population
**What:** The Context Agent (Step 1c) already builds a list of `PlayerPropSnapshotCreate` objects in its loop. Currently those objects are written to DB and discarded. They must also be returned in the partial state dict so LangGraph merges them into `GraphState`.

**When to use:** Any time an agent generates data that a downstream agent needs — keep in state rather than re-fetching.

**Key detail:** The existing loop in `agents.py` (lines 292–315) already constructs `PlayerPropSnapshotCreate` objects. Collect them into a list and include in the return dict:
```python
# In make_context_agent closure — Step 1c block
_prop_snapshots: list = []
for event_data in raw_props:
    for bookmaker in event_data.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            for outcome in market.get("outcomes", []):
                # ... existing snap construction ...
                _prop_snapshots.append(snap)
                write_player_prop_snapshot(snap, ...)

# In the return dict (Step 3)
return {
    "context_signals": signals,
    "situational_params": situational_params,
    "player_prop_snapshots": _prop_snapshots if _prop_snapshots else None,
}
```

### Pattern 3: Snapshot matching in PropArbitrageAgent
**What:** Replace the `context_signals.odds_snapshot` lookup for implied_prob with an iteration over `state["player_prop_snapshots"]`, matching on `prop_type` and `line`.

**When to use:** Whenever the agent needs to find the specific market line matching the prop query.

**Matching key strategy:** `PlayerPropSnapshotCreate` has fields `prop_type`, `line` (Optional[Decimal]), and `player_name`. Match on `prop_type == state["prop_type"]` AND `line == Decimal(str(state["prop_line"]))` (normalise both to Decimal for comparison). Player name matching is optional belt-and-suspenders — the prop_type + line pair is typically unique enough within a snapshot set for a single game.

**Example:**
```python
snapshots: list | None = state.get("player_prop_snapshots")
target_prop_type: str = state.get("prop_type", "")
target_line: Decimal | None = None
raw_line = state.get("prop_line")
if raw_line is not None:
    try:
        target_line = Decimal(str(raw_line))
    except Exception:
        pass

matched_snapshot = None
if snapshots:
    for snap in snapshots:
        type_match = snap.prop_type == target_prop_type
        line_match = (target_line is None) or (snap.line == target_line)
        if type_match and line_match:
            matched_snapshot = snap
            break

if matched_snapshot is None:
    log.info(
        "prop_arbitrage_agent.no_prop_snapshot",
        sport=resolved_sport,
        prop_type=target_prop_type,
        prop_line=str(raw_line),
        reason="no matching PlayerPropSnapshot found in state",
    )
    return _NO_SIGNAL

implied_prob: Decimal = matched_snapshot.implied_probability
```

### Pattern 4: Retaining market_type from snapshot
**What:** `EVSignal.market_type` is currently drawn from `context_signals.odds_snapshot.market_type`. With the new path, use `matched_snapshot.prop_type` as the market_type string. This is more specific and correct (e.g., "player_pass_yds" vs "h2h").

### Anti-Patterns to Avoid
- **DB query inside PropArbitrageAgent:** Phase 5 locked decision — arbitrage math is stateless, no pool. Do not add a pool parameter.
- **Float comparison for line matching:** Never compare `float(snap.line) == float(target_line)` — precision loss; use Decimal equality.
- **Raising exceptions on missing snapshot:** All guards return `_NO_SIGNAL`, never raise — locked Phase 13 pattern for LangGraph continuity.
- **Removing the context_signals.odds_snapshot guard entirely:** Keep it for the game-level arbitrage pipeline (non-prop routes); only bypass it on the prop route when `player_prop_snapshots` is used.
- **Adding player_name to GraphState matching key without confirming PropParams.player_id is stored:** `PropResult` has no `player_name` field — matching on prop_type + line is sufficient. Adding player_name matching requires state["player_name"] which doesn't currently exist.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| American odds to raw implied prob | Custom formula | `sportsbet.quant.vig.american_to_raw_prob` | Already tested, Decimal-safe, handles both positive and negative American odds |
| Devig of matched snapshot | Custom normalization | `remove_vig_multiplicative` / `remove_vig_power` | Already tested with 60-iteration binary search; but note: single-side stored `implied_probability` can be used directly without devigging |
| EV computation | New formula | `sportsbet.arbitrage.ev.compute_ev_percentage` | Locked Phase 5 pattern — floor at 0, Decimal arithmetic |
| Kelly sizing | New formula | `sportsbet.arbitrage.kelly.fractional_kelly` | Locked Phase 2 pattern — 0.25 cap, Decimal arithmetic |
| Trade plan building | New bullet builder | `_build_prop_trade_plan` already in `prop/arbitrage.py` | Function is already correct; only implied_prob source changes |

**Key insight:** The EV formula, Kelly sizing, and trade plan generation are all correct and tested. The only broken piece is the *source* of `implied_prob`. The fix is isolated to how `implied_prob` is extracted — everything downstream is unchanged.

---

## Common Pitfalls

### Pitfall 1: prop_type string format mismatch
**What goes wrong:** The Odds API returns prop_type strings like `"player_pass_yds"` (stored in `player_prop_snapshots.prop_type`), while `PropParams.prop_type` uses shorthand Literals like `"pass_yds"` (stored in `state["prop_type"]`). A naive equality check will always miss.
**Why it happens:** Ingestion normalizes Odds API market keys (e.g., `"player_pass_yards"`) differently from the PropParams Literal set defined in Phase 11.
**How to avoid:** Before writing the match logic, verify the actual strings stored in `PlayerPropSnapshotCreate.prop_type` from the ingestion loop in `agents.py` (line 308: `market.get("key", "unknown")`). Check the Odds API market key format against the PropParams Literals. May need a normalization map or fuzzy match.
**Warning signs:** All prop_arbitrage tests pass but `matched_snapshot` is always `None` in integration — indicates a string format mismatch.

### Pitfall 2: Line comparison precision
**What goes wrong:** `state["prop_line"]` is typed as `Any` in GraphState (Phase 13 decision). It may arrive as a string `"250.5"`, float `250.5`, or Decimal. Direct equality comparison without normalization fails silently.
**Why it happens:** `PropParams.line` is `Decimal`, but callers may pass `str` or `float` to GraphState since `prop_line: Any`.
**How to avoid:** Always normalize both sides to `Decimal(str(...))` before comparison. Use a try/except around the conversion; if conversion fails, treat line_match as True (match on prop_type alone).

### Pitfall 3: player_prop_snapshots not in GraphState
**What goes wrong:** The planner adds snapshot lookup logic in `prop/arbitrage.py` but forgets to add the `player_prop_snapshots` field to `GraphState` TypedDict — causes `state.get("player_prop_snapshots")` to always return `None` (TypedDict access on undefined keys returns None with `.get()`).
**Why it happens:** GraphState changes and agent changes are in different files; easy to miss one.
**How to avoid:** The plan must explicitly include a `state.py` task and a `agents.py` population task as required preconditions to the `arbitrage.py` logic change.

### Pitfall 4: LangGraph get_type_hints() with non-runtime import
**What goes wrong:** If `PlayerPropSnapshotCreate` is imported under `TYPE_CHECKING` guard in `state.py`, LangGraph's `get_type_hints()` call at graph construction time raises `NameError`.
**Why it happens:** LangGraph inspects `GraphState` type hints at runtime; `TYPE_CHECKING`-guarded imports are not resolved at runtime.
**How to avoid:** Locked Phase 4/6/12 pattern — all types used in `GraphState` annotations must be runtime imports, not `TYPE_CHECKING`-only. Use `list[Any]` annotation in GraphState to avoid importing `PlayerPropSnapshotCreate` into `state.py` entirely (follows `prop_filters: dict[str, Any] | None` pattern).

### Pitfall 5: context_signals.odds_snapshot guard removal breaks non-prop routes
**What goes wrong:** Removing the `context_signals.odds_snapshot` guard entirely causes the game-level arbitrage pipeline to fail — it still needs `odds_snapshot` for h2h/spread markets.
**Why it happens:** `PropArbitrageAgent` is wired alongside the regular `ArbitrageAgent` in the graph; both share the `_NO_SIGNAL` early-return pattern.
**How to avoid:** Do NOT remove the existing `odds_snapshot` guard logic from `prop/arbitrage.py` entirely. Instead, add the new prop-snapshot lookup path as an alternative when `player_prop_snapshots` is available in state. Keep the existing guard as a fallback for backward compatibility — or make the prop path conditional on `player_prop_snapshots` being non-None.

### Pitfall 6: Existing tests use context_signals.odds_snapshot — they will break
**What goes wrong:** All tests in `test_prop_arbitrage.py` supply implied_prob through `ContextSignals.odds_snapshot`. After the fix, those tests will no longer exercise the correct code path unless updated.
**Why it happens:** Tests were written in Phase 13 before the gap was identified.
**How to avoid:** The plan must include updating test fixtures to supply `player_prop_snapshots` in state AND assert that `context_signals.odds_snapshot` is no longer the implied_prob source. Retain the existing guard tests (missing odds_snapshot → `_NO_SIGNAL`) but add new tests for the new path.

---

## Code Examples

Verified patterns from existing codebase:

### PlayerPropSnapshotCreate fields (ingestion/prop_odds.py)
```python
# Source: src/sportsbet/ingestion/prop_odds.py
class PlayerPropSnapshotCreate(BaseModel):
    model_config = ConfigDict(strict=True)
    sport: str
    game_id: Optional[str] = None
    player_name: str
    sportsbook: str
    prop_type: str           # raw Odds API market key e.g. "player_pass_yards"
    line: Optional[Decimal] = None
    price: Optional[int] = None   # American odds e.g. -115
    implied_probability: Decimal   # pre-computed: Decimal(str(round(raw_prob, 6)))
```

### Decimal-safe line normalization (established project pattern)
```python
# Pattern from Phase 3/9 decisions — always wrap float/str in Decimal(str(...))
target_line = Decimal(str(state.get("prop_line"))) if state.get("prop_line") is not None else None
```

### _NO_SIGNAL guard return (existing prop/arbitrage.py)
```python
# Source: src/sportsbet/prop/arbitrage.py line 36
_NO_SIGNAL: dict[str, Any] = {"ev_signal": None}
# All guard paths return this — never raise, per Phase 13 locked decision
```

### GraphState field addition for list[Any] (following prop_filters pattern)
```python
# Source: src/sportsbet/graph/state.py — prop_filters pattern (Phase 14)
prop_filters: dict[str, Any] | None  # type: ignore[misc]
# New field follows same pattern:
player_prop_snapshots: list[Any] | None  # type: ignore[misc]
# PlayerPropSnapshotCreate list from context_agent Step 1c (Phase 23 — PROP-06)
```

### american_to_raw_prob (quant/vig.py — for reference if re-devigging)
```python
# Source: src/sportsbet/quant/vig.py
def american_to_raw_prob(american_odds: int) -> Decimal:
    odds = Decimal(str(american_odds))
    if american_odds < 0:
        abs_odds = abs(odds)
        return abs_odds / (abs_odds + Decimal("100"))
    else:
        return Decimal("100") / (odds + Decimal("100"))
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `implied_prob` from `context_signals.odds_snapshot` (h2h moneyline) | `implied_prob` from matching `PlayerPropSnapshot` row (player prop market) | Phase 23 (this fix) | EV comparisons become mathematically commensurable — both probabilities now refer to the same prop outcome |
| No `player_prop_snapshots` in GraphState | `player_prop_snapshots: list[Any] | None` in GraphState | Phase 23 | Prop snapshot data flows from Context Agent to PropArbitrageAgent without a DB round-trip |

**Deprecated/outdated:**
- Reading `context_signals.odds_snapshot.implied_probability` inside `prop_arbitrage_agent` for EV computation: replaced by matched snapshot lookup. The `odds_snapshot` guard remains valid for non-prop arbitrage routes.

---

## Open Questions

1. **Prop_type string normalization between Odds API and PropParams Literals**
   - What we know: `agents.py` line 308 stores `market.get("key", "unknown")` directly — the raw Odds API market key (e.g., `"player_pass_yards"`)
   - What's unclear: Whether PropParams Literals (`"pass_yds"`, `"rush_yds"`, etc.) match the Odds API market keys exactly, or whether a mapping table is needed
   - Recommendation: Inspect actual Odds API market keys at test time (or add a `_PROP_TYPE_ALIAS_MAP` dict in `prop/arbitrage.py`); the plan should include a task to verify or add normalization. As a safe fallback, match on `line` only if prop_type match fails.

2. **Devig strategy for single-side prop snapshot**
   - What we know: `PlayerPropSnapshotCreate.implied_probability` is stored as `Decimal(str(round(raw_prob, 6)))` — this is the *vig-inclusive* raw probability from `american_to_raw_prob`, not a devigged fair probability
   - What's unclear: Whether to use vig-inclusive `implied_probability` directly (simpler, consistent with how `context_signals.odds_snapshot.implied_probability` was used in Phase 13) or to re-devig from `price` using `remove_vig_multiplicative`/`remove_vig_power`
   - Recommendation: Use stored `implied_probability` directly for Phase 23. This matches the existing behavior (Phase 13 `AgentOddsSnapshot.implied_probability` was also vig-inclusive). A devig step on prop odds requires both sides of the market (over + under) which may not be co-located in the matched snapshot.

3. **Multiple snapshots matching same prop_type + line**
   - What we know: Multiple sportsbooks write separate `PlayerPropSnapshotCreate` rows for the same prop; the list in state may have many matches
   - What's unclear: Which sportsbook's implied_prob to use for EV comparison
   - Recommendation: Match on first found (consistent with existing behavior where `context_signals.odds_snapshot` used the single snapshot returned by `_extract_odds_snapshot`). A future improvement could use the sharpest (Pinnacle/Circa) sportsbook's line.

---

## Validation Architecture

`nyquist_validation` is enabled in `.planning/config.json`.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/test_prop_arbitrage.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-06 SC-1 | `prop_arbitrage_agent` reads `state["player_prop_snapshots"]` and matches on player/market/line | unit | `pytest tests/test_prop_arbitrage.py::TestProp06PlayerPropSnapshot -x -q` | ❌ Wave 0 gap |
| PROP-06 SC-2 | `implied_prob` derived from matched `PlayerPropSnapshot.implied_probability` not from `context_signals.odds_snapshot` | unit | `pytest tests/test_prop_arbitrage.py::TestProp06ImpliedProbSource -x -q` | ❌ Wave 0 gap |
| PROP-06 SC-3 | No matching snapshot → `_NO_SIGNAL` with structured log (not crash) | unit | `pytest tests/test_prop_arbitrage.py::TestProp06NoSnapshotGuard -x -q` | ❌ Wave 0 gap |
| PROP-06 SC-4 | EV and Kelly computed from commensurable probs: P(prop outcome) vs implied P(prop outcome) | unit + e2e | `pytest tests/test_prop_arbitrage.py::TestProp06CommensurableEV -x -q` | ❌ Wave 0 gap |
| PROP-06 existing | Existing PROP-06 tests updated to supply `player_prop_snapshots` in state and remain GREEN | unit | `pytest tests/test_prop_arbitrage.py -x -q` | ✅ exists, needs update |

### Sampling Rate
- **Per task commit:** `pytest tests/test_prop_arbitrage.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] New test class `TestProp06PlayerPropSnapshot` in `tests/test_prop_arbitrage.py` — covers SC-1/SC-2: state supplies `player_prop_snapshots` list, asserts `matched_snapshot.implied_probability` is used for EV
- [ ] New test class `TestProp06NoSnapshotGuard` in `tests/test_prop_arbitrage.py` — covers SC-3: state has empty/None `player_prop_snapshots`, asserts `ev_signal=None` with log
- [ ] Update `_make_nfl_state` and `_make_nba_state` fixtures to include `player_prop_snapshots` containing a `PlayerPropSnapshotCreate` with matching prop_type/line

---

## Sources

### Primary (HIGH confidence)
- Direct code read: `src/sportsbet/prop/arbitrage.py` — full current implementation of PropArbitrageAgent
- Direct code read: `src/sportsbet/graph/models.py` — `PropResult`, `EVSignal`, `AgentOddsSnapshot`, `ContextSignals` models
- Direct code read: `src/sportsbet/graph/state.py` — full GraphState TypedDict with all existing fields
- Direct code read: `src/sportsbet/db/models.py` — `PlayerPropSnapshot` ORM model schema
- Direct code read: `src/sportsbet/ingestion/prop_odds.py` — `PlayerPropSnapshotCreate` Pydantic model
- Direct code read: `src/sportsbet/graph/agents.py` lines 270–320 — Step 1c prop snapshot ingestion loop
- Direct code read: `src/sportsbet/quant/vig.py` — `american_to_raw_prob`, `remove_vig_multiplicative`, `remove_vig_power`
- Direct code read: `src/sportsbet/arbitrage/ev.py` — `compute_ev_percentage`
- Direct code read: `src/sportsbet/arbitrage/kelly.py` — `fractional_kelly`
- Direct code read: `tests/test_prop_arbitrage.py` — existing PROP-06/PROP-07 test suite

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` decisions log — Phase 5, 13, 14 locked decisions on stateless arbitrage, partial state return patterns, GraphState field additions

---

## Metadata

**Confidence breakdown:**
- Bug diagnosis (what is wrong): HIGH — direct code inspection confirms `context_signals.odds_snapshot.implied_probability` is an h2h game-winner probability, not a prop market probability
- Fix approach (player_prop_snapshots in state): HIGH — follows established Phase 14 pattern for prop_filters, prop_type, prop_line
- prop_type string normalization: MEDIUM — Odds API market keys vs PropParams Literals not yet verified to match; open question flagged
- Devig strategy for single-side snapshot: HIGH — recommendation to use stored vig-inclusive implied_probability is consistent with how Phase 13 used AgentOddsSnapshot.implied_probability
- Test scope: HIGH — existing test file is the correct target; new test classes required

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable codebase; no external API dependencies in the fix itself)
