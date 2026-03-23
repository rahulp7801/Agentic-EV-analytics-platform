# Phase 13: Player Prop Arbitrage and Full Pipeline Wiring - Research

**Researched:** 2026-03-23
**Domain:** PropArbitrageAgent, CorrelationGuard extension, LangGraph prop pipeline wiring
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-06 | `PropArbitrageAgent` flags mispriced player props by comparing `PropResult.true_probability` against sportsbook implied probability, outputting raw EV percentage and a 3-bullet Trade Plan thesis with fractional Kelly sizing — no flat bet sizes | Existing `compute_ev_percentage`, `build_trade_plan`, `fractional_kelly`, and `make_arbitrage_agent` in Phase 5 are the direct template; Phase 13 wraps `PropResult` instead of `QuantResult` |
| PROP-07 | `CorrelationGuard` is extended with a prop conflict matrix that blocks simultaneous correlated prop exposures (e.g., Over passing yards + Under receiving yards on the same game) | Existing `CONFLICT_PAIRS` frozenset pattern in `correlation_guard.py` is structurally identical; extend with prop-to-prop and prop-to-game-total pairs |
</phase_requirements>

---

## Summary

Phase 13 is the final integration phase for v1. It wires the NFL and NBA prop quant signals produced in Phases 11 and 12 into an end-to-end arbitrage pipeline: `PropArbitrageAgent` computes EV% from `PropResult.true_probability` vs. the sportsbook implied probability from `PlayerPropSnapshot`, produces a 3-bullet Trade Plan, and outputs fractional Kelly sizing. `CorrelationGuard` receives a new prop conflict matrix layer that blocks prop-to-prop correlations (e.g., Over passing yards + Under receiving yards on the same target) and prop-to-game-total correlations. The LangGraph graph is extended with `prop_quant_node`, `nba_quant_node`, and `prop_arbitrage_node`, and `route_from_master` gains two new routing keys (`prop_analysis` is already wired; `nba_prop_analysis` and `prop_arbitrage_analysis` are needed).

The implementation is almost entirely assembly — every primitive already exists. `PropArbitrageAgent` is structurally identical to `make_arbitrage_agent` (Phase 5), but reads `PropResult` from `state["prop_result"]` or `state["nba_prop_result"]` instead of `state["quant_result"]`, and reads the sportsbook implied probability from `PlayerPropSnapshot` rather than `AgentOddsSnapshot`. The CorrelationGuard extension adds new entries to `CONFLICT_PAIRS`; no class changes are needed. The graph wiring follows the exact same optional-node injection pattern from Phases 5–12.

**Primary recommendation:** Implement `make_prop_arbitrage_agent` in `src/sportsbet/prop/arbitrage.py` mirroring `make_arbitrage_agent`; extend `CONFLICT_PAIRS` in `correlation_guard.py` with prop-specific pairs; wire `prop_quant_node`, `nba_quant_node`, and `prop_arbitrage_node` into `create_graph()` and `create_graph_with_sqlite()`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python Decimal | stdlib | All probability/fraction arithmetic | Prevents float precision loss in Kelly formula; established in Phase 2 |
| asyncpg | installed | Pool-bound agent closures | Established pattern from Phases 3–12 |
| Pydantic v2 | installed | I/O model validation gate | Non-negotiable per CLAUDE.md; `ConfigDict(strict=True)` on all models |
| LangGraph | 1.1.0 | StateGraph node/edge wiring | Established from Phase 2 |
| structlog | installed | Agent logging | Consistent with all prior agent closures |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| langgraph.checkpoint.memory.MemorySaver | 1.1.0 | Test isolation | All new tests — no disk I/O |
| pytest + asyncio.run() | installed | Async agent test runner | Matches Phase 5 and Phase 11 test patterns |
| unittest.mock.MagicMock / AsyncMock | stdlib | Pool mocking in unit tests | Matches test_prop_executor.py / test_arbitrage.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Extending CONFLICT_PAIRS frozenset | New CorrelationGuard subclass | New entries require zero class changes; frozenset extension is O(1) membership, matches Phase 5 design |
| New `ArbitrageSignal` Pydantic model | Reuse existing `EVSignal` | EVSignal already has all required fields (ev_percentage, kelly_fraction, trade_plan, market_type); adding a new model introduces duplication with no benefit |
| `PropOddsSnapshot` as separate model | Reuse `AgentOddsSnapshot` | `AgentOddsSnapshot.market_type` is a free string; it can carry `"player_prop:pass_yds"` or similar; no schema change needed |

**Installation:** All dependencies are already installed. No new packages required.

---

## Architecture Patterns

### Recommended Project Structure

The new code is distributed across existing packages. No new packages:

```
src/sportsbet/
├── prop/
│   ├── agents.py           # existing: make_prop_quant_agent (Phase 11)
│   ├── nba_agents.py       # existing: make_nba_quant_agent (Phase 12)
│   ├── arbitrage.py        # NEW: make_prop_arbitrage_agent (Phase 13 Plan 01)
│   └── ...
├── arbitrage/
│   ├── correlation_guard.py # existing: extend CONFLICT_PAIRS with prop pairs
│   └── ...
└── graph/
    ├── graph.py            # existing: extend create_graph() + create_graph_with_sqlite()
    ├── router.py           # existing: extend route_from_master() with new request_types
    └── state.py            # existing: add prop_ev_signal to GraphState if needed
```

### Pattern 1: PropArbitrageAgent Closure Factory

**What:** `make_prop_arbitrage_agent(settings_override)` mirrors `make_arbitrage_agent` from Phase 5 but reads `PropResult` instead of `QuantResult`. Stateless — no DB access.

**When to use:** When `request_type` is `"prop_arbitrage_analysis"`.

**Example:**
```python
# Source: mirrors src/sportsbet/graph/agents.py make_arbitrage_agent (Phase 5)
def make_prop_arbitrage_agent(
    settings_override=None,
    sport: str = "nfl",  # "nfl" reads prop_result; "nba" reads nba_prop_result
):
    from sportsbet.arbitrage.ev import build_trade_plan, compute_ev_percentage
    from sportsbet.arbitrage.kelly import fractional_kelly
    from sportsbet.config import settings as _settings

    cfg = settings_override if settings_override is not None else _settings

    async def prop_arbitrage_agent(state: GraphState) -> dict:
        # Resolve which prop_result to use based on sport
        if sport == "nba":
            prop_result = state.get("nba_prop_result")
        else:
            prop_result = state.get("prop_result")

        context_signals = state.get("context_signals")

        # Guards: identical to make_arbitrage_agent
        if prop_result is None or prop_result.true_probability is None:
            return {"ev_signal": None}
        if context_signals is None or context_signals.odds_snapshot is None:
            return {"ev_signal": None}

        snapshot = context_signals.odds_snapshot
        true_prob = prop_result.true_probability
        implied_prob = snapshot.implied_probability

        ev_pct = compute_ev_percentage(true_prob, implied_prob)
        if ev_pct == Decimal("0"):
            return {"ev_signal": None}

        kelly_frac = fractional_kelly(
            p=true_prob,
            b=Decimal("1.0"),
            fraction=Decimal(str(cfg.max_kelly_fraction)),
        )

        # Build prop-context trade plan (bullet 3 includes prop line + sport)
        trade_plan = _build_prop_trade_plan(
            ev_pct, kelly_frac,
            context_signals.injury_flags,
            snapshot.market_type,
            prop_result,
        )

        signal = EVSignal(
            ev_percentage=ev_pct,
            true_probability=true_prob,
            implied_probability=implied_prob,
            kelly_fraction=kelly_frac,
            trade_plan=trade_plan,
            market_type=snapshot.market_type,
        )
        return {"ev_signal": signal, "pending_signals": [signal]}

    return prop_arbitrage_agent
```

**Key design note:** The agent is sport-agnostic at the math level; the `sport` parameter only determines which state key to read (`prop_result` vs `nba_prop_result`). A single factory can handle both by accepting a `sport` parameter — or two separate factories can be provided to avoid conditional branching.

### Pattern 2: Extending CONFLICT_PAIRS

**What:** Add new `frozenset` entries to the module-level `CONFLICT_PAIRS` in `correlation_guard.py`. No class changes.

**When to use:** Any time a new prop market conflict is identified.

**Example:**
```python
# Source: src/sportsbet/arbitrage/correlation_guard.py (Phase 5 pattern)
# Extend with prop-specific conflict pairs for PROP-07
CONFLICT_PAIRS: frozenset[frozenset[str]] = frozenset({
    # --- Existing game-total conflicts (Phase 5) ---
    frozenset({"over_passing_yards", "under_total_points"}),
    frozenset({"over_rushing_yards", "over_total_points"}),
    frozenset({"over_passing_yards", "under_passing_yards"}),
    frozenset({"over_total_points", "under_total_points"}),

    # --- New prop-to-prop conflicts (Phase 13, PROP-07) ---
    # QB passing yards and primary receiver yards are positively correlated
    frozenset({"over_pass_yds", "under_rec_yds"}),       # req: PROP-07 explicit
    frozenset({"under_pass_yds", "over_rec_yds"}),
    # Passing TDs and receiving TDs share the same event
    frozenset({"over_pass_tds", "under_rec_tds"}),
    frozenset({"under_pass_tds", "over_rec_tds"}),

    # --- Prop-to-game-total conflicts (Phase 13, PROP-07) ---
    frozenset({"over_pass_yds", "under_total_points"}),  # high passing -> more scoring
    frozenset({"over_rush_yds", "under_total_points"}),  # rushed clock -> fewer points?
    # NBA: player volume props vs opponent defense context
    frozenset({"over_points", "under_total_points"}),
})
```

**Critical constraint:** Market type strings in `EVSignal.market_type` must be consistent between the arbitrage agent and the guard — if `AgentOddsSnapshot.market_type` returns `"pass_yds"`, use that verbatim; if it returns `"player_pass_yds"`, use that. The guard checks exact string equality.

### Pattern 3: Graph Wiring

**What:** Add `prop_quant_node`, `nba_quant_node`, `prop_arbitrage_node` as optional parameters to `create_graph()` and wire them in `create_graph_with_sqlite()`.

**When to use:** Same optional-node injection pattern used in all phases 3–12.

**Example:**
```python
# Source: src/sportsbet/graph/graph.py (established pattern)
def create_graph(
    ...
    prop_quant_node: Any = None,       # NEW Phase 13
    nba_quant_node: Any = None,        # NEW Phase 13
    prop_arbitrage_node: Any = None,   # NEW Phase 13
) -> CompiledStateGraph:
    # ... existing node registrations ...

    # Stubs for backward-compat
    active_prop_quant_node = prop_quant_node if prop_quant_node is not None else _prop_quant_stub
    active_nba_quant_node = nba_quant_node if nba_quant_node is not None else _nba_quant_stub
    active_prop_arbitrage_node = prop_arbitrage_node if prop_arbitrage_node is not None else _prop_arb_stub

    builder.add_node("prop_quant_agent", active_prop_quant_node)
    builder.add_node("nba_quant_agent", active_nba_quant_node)
    builder.add_node("prop_arbitrage_agent", active_prop_arbitrage_node)

    # Route prop_analysis -> prop_quant_agent (already in router.py)
    # Route nba_prop_analysis -> nba_quant_agent (NEW)
    # Route prop_arbitrage_analysis -> prop_arbitrage_agent (NEW)
    builder.add_edge("prop_quant_agent", "prop_arbitrage_agent")
    builder.add_edge("nba_quant_agent", "prop_arbitrage_agent")

    # prop_arbitrage flows through existing correlation_guard -> aggregator -> END
    # when those nodes are provided; else -> END
```

**Alternative topology:** `prop_quant_agent -> END` and `prop_arbitrage_agent` triggered separately. This requires two ainvoke calls. Prefer the chained topology (quant -> arbitrage) to match the v1 pipeline contract in the Phase 13 success criteria.

### Pattern 4: Route Extension

**What:** Add `"nba_prop_analysis"` and `"prop_arbitrage_analysis"` to `route_from_master`.

**Note:** `"prop_analysis"` already routes to `"prop_quant_agent"` in `router.py` (Phase 11 wiring). The planner must verify whether a separate `"prop_arbitrage_analysis"` is needed or whether the existing prop route chain is sufficient.

```python
# Extend route_from_master() in router.py:
elif request_type == "nba_prop_analysis":
    return "nba_quant_agent"
elif request_type == "prop_arbitrage_analysis":
    return "prop_arbitrage_agent"
```

**Conditional edges map** must also include `"nba_quant_agent"` and `"prop_arbitrage_agent"` in `create_graph()`.

### Anti-Patterns to Avoid

- **Separate ArbitrageSignal model:** Do not create a new `PropArbitrageSignal` Pydantic model; `EVSignal` already satisfies all PROP-06 constraints (ev_percentage, kelly_fraction, trade_plan, market_type).
- **LLM-generated trade plan text:** The 3-bullet trade plan must be constructed from `PropResult` numeric fields (`true_probability`, `mean_stat`, `sample_size`) — never from LLM inference.
- **Float in Kelly formula:** All Kelly arithmetic must stay in `Decimal`; use `Decimal(str(cfg.max_kelly_fraction))` not direct float assignment.
- **Mutable CONFLICT_PAIRS:** The frozenset is immutable by design; new pairs must be declared at module level, not added at runtime.
- **prop_quant_agent already defined elsewhere:** `make_prop_quant_agent` lives in `src/sportsbet/prop/agents.py`. The graph wiring imports it from there; do not duplicate in `graph/agents.py`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| EV calculation | Custom probability comparator | `compute_ev_percentage` from `sportsbet.arbitrage.ev` | Already correct, tested, floors at 0 |
| Kelly sizing | Custom bet sizer | `fractional_kelly` from `sportsbet.arbitrage.kelly` | Hard cap at 0.25, tested, all-Decimal |
| Trade plan formatting | Custom string builder | `build_trade_plan` from `sportsbet.arbitrage.ev` | Returns exactly 3 bullets per EVSignal constraint |
| Conflict detection | Custom graph search | `CorrelationGuard.check()` + extended `CONFLICT_PAIRS` | O(n * |CONFLICT_PAIRS|) membership check, already tested |
| Daily drawdown gate | Custom limit tracker | `Aggregator` from `sportsbet.arbitrage.aggregator` | Stateful, correct gate-on-limit semantics |
| Pydantic validation | Manual dict checks | `PropResult`, `EVSignal`, `PropParams` from `sportsbet.graph.models` | strict=True, Decimal fields, all validated |

**Key insight:** Phase 13 is predominantly wiring and extension. Every primitive component exists; the work is connecting them with correct state key reads and routing.

---

## Common Pitfalls

### Pitfall 1: Wrong State Key for PropResult

**What goes wrong:** Agent reads `state.get("quant_result")` instead of `state.get("prop_result")` or `state.get("nba_prop_result")`.
**Why it happens:** `make_arbitrage_agent` reads `quant_result`; copy-paste without adaptation.
**How to avoid:** `make_prop_arbitrage_agent` must explicitly determine which key to read based on `sport` parameter or `request_type` in state.
**Warning signs:** `ev_signal=None` even when `prop_result.true_probability` is set; check agent logs for `"prop_arbitrage_agent_no_prop_result"`.

### Pitfall 2: Odds Snapshot Market Type Mismatch with CONFLICT_PAIRS

**What goes wrong:** `AgentOddsSnapshot.market_type` for a player prop might be `"player_pass_yds"` or just `"pass_yds"` depending on how The Odds API formats the market key. If `CONFLICT_PAIRS` uses `"over_pass_yds"` but the snapshot has `"player_pass_yds:over"`, the guard never fires.
**Why it happens:** The Odds API market key format for player props is different from game markets.
**How to avoid:** Normalize `market_type` to a canonical form (e.g., `"over_pass_yds"`) at the point where `AgentOddsSnapshot` is constructed in the prop odds path. Check `OddsAPIPoller.fetch_player_props()` output format.
**Warning signs:** CorrelationGuard always passes all signals through; log `market_types_present` in `check()` to inspect.

### Pitfall 3: prop_quant_agent / nba_quant_agent not registered in conditional_edges map

**What goes wrong:** Node registered with `add_node()` but not added to the conditional edges routing table dict in `add_conditional_edges()`.
**Why it happens:** LangGraph requires both `add_node()` and a corresponding entry in the conditional edges `{str: str}` mapping dict.
**How to avoid:** Add `"prop_quant_agent": "prop_quant_agent"`, `"nba_quant_agent": "nba_quant_agent"`, `"prop_arbitrage_agent": "prop_arbitrage_agent"` to the conditional edges dict in `create_graph()`.
**Warning signs:** `KeyError` or `NodeNotFoundError` on `ainvoke` with `request_type="nba_prop_analysis"`.

### Pitfall 4: Pipeline Topology — quant then arbitrage in one ainvoke

**What goes wrong:** The end-to-end test (Success Criteria 3) requires both quant AND arbitrage to run in a single pipeline invocation. If quant and arbitrage are separate routing branches (not chained), two separate `ainvoke` calls are needed, which breaks the "end-to-end pipeline run" contract.
**Why it happens:** The existing `prop_analysis` route only runs `prop_quant_agent -> END`. Arbitrage is not chained.
**How to avoid:** Either (a) chain `prop_quant_agent -> prop_arbitrage_agent -> correlation_guard -> aggregator -> END`, or (b) use a compound request type `"prop_full_pipeline"` that chains all nodes. Option (a) is the cleaner v1 approach.
**Warning signs:** Integration test returns `ev_signal=None` because arbitrage node never ran.

### Pitfall 5: GraphState missing `prop_type` and `prop_line` fields

**What goes wrong:** `prop_quant_agent` reads `state.get("prop_type", "pass_yds")` and `state.get("prop_line", "0")`, but GraphState TypedDict does not formally declare these fields. In integration tests with `TypedDict` strict checking, missing keys cause `KeyError`.
**Why it happens:** These fields were added as informal state conventions in Phase 11 but not declared in the TypedDict.
**How to avoid:** Ensure `prop_type: str` and `prop_line: Any` (or `Decimal | str | int | None`) are declared in `GraphState` in `state.py` before Phase 13 tests run. Check whether Phase 11/12 already added them.
**Warning signs:** `KeyError: 'prop_type'` in integration test initial state construction.

### Pitfall 6: Decimal(str()) conversion for prop_line in integration tests

**What goes wrong:** Integration test passes `prop_line=22.5` as a Python float in the initial state dict; `Decimal(str(22.5))` works correctly, but `Decimal(22.5)` produces `Decimal('22.4999999...')` due to float representation.
**Why it happens:** Existing Phase 11 code uses `Decimal(str(prop_line_raw))` — this is correct — but tests must also use strings or Decimal-compatible inputs.
**How to avoid:** Always set `prop_line="22.5"` or `Decimal("22.5")` in test state dicts, never bare float.

### Pitfall 7: NBAContextSignals not in GraphState for NBA integration test

**What goes wrong:** NBA end-to-end integration test omits `nba_context_signals` from initial state; `_apply_nba_context_adjustments` returns base probability unchanged (no error, just no adjustment), causing a different probability than expected.
**Why it happens:** `nba_context_signals` is Optional; the adjustment silently no-ops.
**How to avoid:** Explicitly include `NBAContextSignals(opponent_def_rating=..., pace_factor=..., rest_days=..., is_home=...)` in integration test initial state.

---

## Code Examples

Verified patterns from existing codebase:

### PropResult guard pattern (mirrors QuantResult guard in make_arbitrage_agent)
```python
# Source: src/sportsbet/graph/agents.py make_arbitrage_agent (Phase 5)
from sportsbet.graph.models import PropResult

prop_result = state.get("prop_result")
if prop_result is None or not isinstance(prop_result, PropResult):
    return {"ev_signal": None, "error": "prop_result missing or invalid"}
if prop_result.true_probability is None:
    return {"ev_signal": None}
```

### Prop-specific trade plan bullet 3 (include prop line context)
```python
# Source: pattern from src/sportsbet/arbitrage/ev.py build_trade_plan
def _build_prop_trade_plan(
    ev_pct: Decimal,
    kelly_frac: Decimal,
    injury_flags: dict[str, str],
    market_type: str,
    prop_result: PropResult,
) -> list[str]:
    bullet_1 = f"+{float(ev_pct):.1%} EV edge on {market_type} prop market"
    bullet_2 = (
        f"Kelly sizing: {float(kelly_frac):.1%} fractional stake "
        f"(sample_size={prop_result.sample_size}, mean={float(prop_result.mean_stat or 0):.1f})"
    )
    if injury_flags:
        flagged = ", ".join(f"{p} ({s})" for p, s in injury_flags.items())
        bullet_3 = f"Material injury flags: {flagged}"
    else:
        bullet_3 = "No material injury flags — proceed with model confidence"
    return [bullet_1, bullet_2, bullet_3]
```

### CONFLICT_PAIRS extension (append-only, module level)
```python
# Source: src/sportsbet/arbitrage/correlation_guard.py (Phase 5 pattern)
# Replace the existing frozenset definition with an extended one
CONFLICT_PAIRS: frozenset[frozenset[str]] = frozenset({
    # Existing (Phase 5)
    frozenset({"over_passing_yards", "under_total_points"}),
    frozenset({"over_rushing_yards", "over_total_points"}),
    frozenset({"over_passing_yards", "under_passing_yards"}),
    frozenset({"over_total_points", "under_total_points"}),
    # New prop-to-prop (Phase 13 — PROP-07)
    frozenset({"over_pass_yds", "under_rec_yds"}),   # PROP-07 explicit requirement
    frozenset({"under_pass_yds", "over_rec_yds"}),
    frozenset({"over_pass_tds", "under_rec_tds"}),
    frozenset({"under_pass_tds", "over_rec_tds"}),
    # New prop-to-game-total (Phase 13 — PROP-07)
    frozenset({"over_pass_yds", "under_total_points"}),
    frozenset({"over_rush_yds", "under_total_points"}),
})
```

### Integration test pattern (end-to-end, no DB)
```python
# Source: tests/test_arbitrage.py test_e2e_pipeline (Phase 5 pattern)
async def test_prop_pipeline_nfl():
    from langgraph.checkpoint.memory import MemorySaver
    import uuid, asyncio
    from decimal import Decimal
    from datetime import datetime, timezone
    from sportsbet.graph.models import (
        AgentOddsSnapshot, ContextSignals, PropResult, NBAContextSignals
    )

    state = {
        "session_id": str(uuid.uuid4()),
        "request_type": "prop_full_pipeline",
        "created_at": datetime.now(timezone.utc),
        "game_id": "2024_01_KC_LV",
        "season": 2024, "week": 1,
        "home_team": "KC", "away_team": "LV",
        "injury_flags": {}, "weather_json": None, "error": None,
        "quant_result": None, "ev_signal": None,
        "context_signals": ContextSignals(
            game_id="2024_01_KC_LV", injury_flags={},
            odds_snapshot=AgentOddsSnapshot(
                game_id="2024_01_KC_LV", sportsbook="draftkings",
                market_type="over_pass_yds",
                implied_probability=Decimal("0.50"),
                snapped_at=datetime.now(timezone.utc),
            ),
            signals_captured_at=datetime.now(timezone.utc),
        ),
        # Pre-inject PropResult (bypasses DB for unit test)
        "prop_result": PropResult(
            true_probability=Decimal("0.62"),
            sample_size=45,
            confidence_interval=(Decimal("0.54"), Decimal("0.70")),
            data_source="postgresql",
            mean_stat=Decimal("265.0"),
        ),
        "nba_prop_result": None,
        "pending_signals": [], "cleared_signals": [],
        "receiver_gsis_id": "", "kinematic_result": None,
        "prop_type": "pass_yds", "prop_line": "250.5",
        "nba_context_signals": None,
    }

    graph = create_graph(
        checkpointer=MemorySaver(),
        prop_arbitrage_node=make_prop_arbitrage_agent(sport="nfl"),
        correlation_guard_node=make_correlation_guard_node(),
        aggregator_node=make_aggregator_node(bankroll_usd=100000.0, daily_drawdown_limit=0.20),
    )
    result = asyncio.run(graph.ainvoke(state, config={"configurable": {"thread_id": str(uuid.uuid4())}}))
    assert result["ev_signal"] is not None
    assert result["ev_signal"].ev_percentage > Decimal("0")
    assert len(result["ev_signal"].trade_plan) == 3
    assert Decimal("0") < result["ev_signal"].kelly_fraction <= Decimal("0.25")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single `make_arbitrage_agent` for game-level markets | Separate `make_prop_arbitrage_agent` for player prop markets | Phase 13 | Cleaner separation; prop agent reads `PropResult` not `QuantResult` |
| CorrelationGuard covers only game-level market pairs | CorrelationGuard covers prop-to-prop and prop-to-game-total | Phase 13 | PROP-07 compliance |
| `route_from_master` has 5 routes (up to Phase 12) | 7–8 routes after Phase 13 | Phase 13 | `nba_prop_analysis` and `prop_arbitrage_analysis` added |

**Deprecated/outdated:**
- None. Phase 13 extends, not replaces, existing architecture.

---

## Open Questions

1. **GraphState `prop_type` and `prop_line` formal declaration**
   - What we know: Phase 11 uses `state.get("prop_type", "pass_yds")` and `state.get("prop_line", "0")` informally.
   - What's unclear: Whether `prop_type: str` and `prop_line: Any` were added to the `GraphState` TypedDict during Phase 11/12 execution. Checking `state.py` shows they are NOT currently declared as named fields.
   - Recommendation: Plan 01 Wave 0 must add `prop_type: str` and `prop_line: Any` to `GraphState` in `state.py` to avoid integration test fragility. Use `Optional` with defaults for backward-compat.

2. **Market type string normalization for player props**
   - What we know: `AgentOddsSnapshot.market_type` is a free string. The Odds API returns market keys like `"player_pass_yds"` for player prop markets.
   - What's unclear: Whether existing `OddsAPIPoller.fetch_player_props()` normalizes these to short forms like `"pass_yds"` or `"over_pass_yds"`.
   - Recommendation: Plan 01 must define a canonical market type mapping (e.g., `"player_pass_yds"` -> `"pass_yds"`) and ensure `CONFLICT_PAIRS` strings match the canonical form. Check `src/sportsbet/ingestion/odds_poller.py` for prop market key format.

3. **Chained pipeline topology vs. separate request types**
   - What we know: Success Criteria 3 requires "an end-to-end pipeline run (Context → PropQuant → PropArbitrage → Aggregator)". This implies a single `ainvoke` producing an EV signal.
   - What's unclear: Whether the planner should chain `prop_quant_agent -> prop_arbitrage_agent` in the graph (one route), or require two separate ainvoke calls.
   - Recommendation: Chain in-graph: `prop_analysis` route runs `prop_quant_agent -> prop_arbitrage_agent -> correlation_guard -> aggregator -> END`. This matches the Phase 5 chained arbitrage pipeline and satisfies the single-ainvoke contract.

4. **NBA pipeline EV signal against real database data**
   - What we know: Success Criteria 3 requires a non-None EV signal against real database data for both NFL and NBA.
   - What's unclear: Whether a live DB test is required or whether a pre-injected `PropResult` from fixture data is acceptable as "against real database data".
   - Recommendation: The Phase 11/12 pattern uses `SPORTSBET_TEST_DATABASE_URL` gating for DB tests, with mocked pool for unit tests. Success Criteria 3 can be satisfied with a live DB integration test (skipif no DB URL) plus a mock-pool smoke test that exercises the full graph topology.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (installed, pyproject.toml configured) |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` with `pythonpath = ['src', 'site-packages']` |
| Quick run command | `python -m pytest tests/test_prop_arbitrage.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-06 | `PropArbitrageAgent` returns `EVSignal` with EV%, 3-bullet plan, fractional Kelly | unit | `python -m pytest tests/test_prop_arbitrage.py::test_prop06_ev_signal_produced -x` | ❌ Wave 0 |
| PROP-06 | `EVSignal.kelly_fraction` in (0, 0.25] — never flat | unit | `python -m pytest tests/test_prop_arbitrage.py::test_prop06_kelly_fraction_non_flat -x` | ❌ Wave 0 |
| PROP-06 | Negative EV (true_prob < implied) returns `ev_signal=None` | unit | `python -m pytest tests/test_prop_arbitrage.py::test_prop06_no_ev_suppressed -x` | ❌ Wave 0 |
| PROP-06 | Trade plan has exactly 3 non-empty bullets | unit | `python -m pytest tests/test_prop_arbitrage.py::test_prop06_trade_plan_length -x` | ❌ Wave 0 |
| PROP-07 | `CorrelationGuard` blocks Over pass_yds + Under rec_yds simultaneously | unit | `python -m pytest tests/test_prop_arbitrage.py::test_prop07_prop_conflict_blocked -x` | ❌ Wave 0 |
| PROP-07 | `CONFLICT_PAIRS` contains required prop-to-prop pairs | unit | `python -m pytest tests/test_prop_arbitrage.py::test_prop07_conflict_pairs_extended -x` | ❌ Wave 0 |
| PROP-06+07 | Full NFL pipeline (pre-injected PropResult) → non-None EV signal | integration | `python -m pytest tests/test_prop_arbitrage.py::test_e2e_nfl_prop_pipeline -x` | ❌ Wave 0 |
| PROP-06+07 | Full NBA pipeline (pre-injected nba_prop_result) → non-None EV signal | integration | `python -m pytest tests/test_prop_arbitrage.py::test_e2e_nba_prop_pipeline -x` | ❌ Wave 0 |
| PROP-06+07 | Live DB end-to-end (NFL + NBA with real data) | integration/DB | `python -m pytest tests/test_prop_arbitrage.py::test_e2e_live_db -x` (skipif no DB URL) | ❌ Wave 0 |
| PROP-07 | Non-conflicting prop passes guard unchanged | unit | `python -m pytest tests/test_prop_arbitrage.py::test_prop07_no_conflict_passes -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_prop_arbitrage.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_prop_arbitrage.py` — all PROP-06 and PROP-07 test stubs (10 tests)
- [ ] `src/sportsbet/prop/arbitrage.py` — `make_prop_arbitrage_agent` (not yet created)
- [ ] GraphState additions: `prop_type: str` and `prop_line: Any` formal declaration in `state.py`

*(Existing test infrastructure: pytest, conftest.py, MemorySaver pattern — all in place. No new framework install needed.)*

---

## Sources

### Primary (HIGH confidence)
- `src/sportsbet/arbitrage/` (ev.py, kelly.py, correlation_guard.py, aggregator.py) — direct Phase 5 implementation; Phase 13 is a prop-layer wrapper around these same functions
- `src/sportsbet/graph/agents.py` — `make_arbitrage_agent` is the exact template for `make_prop_arbitrage_agent`
- `src/sportsbet/graph/graph.py` — optional-node injection pattern used consistently across Phases 5–12
- `src/sportsbet/graph/state.py` — current GraphState field inventory
- `src/sportsbet/prop/agents.py` — `make_prop_quant_agent` (Phase 11)
- `src/sportsbet/prop/nba_agents.py` — `make_nba_quant_agent` (Phase 12)
- `src/sportsbet/graph/models.py` — `PropResult`, `EVSignal`, `PropParams`, `NBAContextSignals`
- `src/sportsbet/graph/router.py` — current routing table; shows `"prop_analysis"` is already wired
- `.planning/REQUIREMENTS.md` — PROP-06, PROP-07 specification
- `.planning/STATE.md` — all locked decisions from Phases 1–12
- `tests/test_arbitrage.py` — end-to-end test patterns for Phase 13 to mirror

### Secondary (MEDIUM confidence)
- LangGraph 1.1.0 `StateGraph.add_node` + `add_conditional_edges` — established API usage confirmed by all prior phases
- Pydantic v2 `model_copy(update=...)` — used in Phase 11 and 12 for PropResult mutation without re-validation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries established in prior phases, no new dependencies
- Architecture: HIGH — all patterns directly observable in Phase 5/11/12 code
- Pitfalls: HIGH — identified from direct code inspection, not speculation
- Open questions: MEDIUM — require plan-time verification (state.py field check, odds market key format)

**Research date:** 2026-03-23
**Valid until:** Stable indefinitely (internal codebase, no external API changes in scope)
