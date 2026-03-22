# Phase 7: Production Runtime Wiring - Research

**Researched:** 2026-03-22
**Domain:** LangGraph graph factory wiring, TypedDict schema extension, Pydantic devig pipeline integration
**Confidence:** HIGH

## Summary

Phase 7 is a pure integration/wiring phase with no new business logic. Every component being connected already exists and is individually tested. The audit (v1.0-MILESTONE-AUDIT.md) precisely identified three structural gaps that prevent the production runtime from using any of the Phase 5/6 work: `create_graph_with_sqlite()` never passes the four new nodes it needs to receive, `GraphState` is missing the `receiver_gsis_id` field that `make_kinematic_agent` silently reads via `.get()`, and `_extract_odds_snapshot()` does inline American-odds math instead of calling `sportsbet.quant.vig`.

All three gaps are surgical code changes in three files: `graph.py`, `state.py`, and `agents.py`. The vig integration is the most nuanced because it changes a computed value (`implied_probability`) that flows directly into `compute_ev_percentage` — the devigged probability will always be lower than the vig-inclusive raw probability, so any test asserting a specific EV value must be updated to use the devigged figure.

**Primary recommendation:** One plan, one wave — three targeted file edits plus a smoke test confirming all four nodes are reachable via `create_graph_with_sqlite()`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| QUANT-02 | System converts raw sportsbook odds to implied probabilities with configurable vig removal method | `american_to_raw_prob` + `remove_vig_multiplicative` exist in `sportsbet.quant.vig` and are fully tested — need only be imported and called inside `_extract_odds_snapshot()` |
| ARBT-01 | Arbitrage Agent flags +EV discrepancies using true vs. implied probability | Currently receives vig-inclusive `implied_probability`; wiring vig removal makes EV math correct per CLAUDE.md mathematical rigor requirement |
| ARBT-03 | CorrelationGuard node enforces hardcoded conflict stops before any signal is output | Wired in `create_graph()` but never in `create_graph_with_sqlite()` — add `make_correlation_guard_node()` call and pass result as param |
| ARBT-04 | Aggregator node enforces daily drawdown gate | Same gap as ARBT-03 — `make_aggregator_node(bankroll, limit)` already exists, never instantiated in `create_graph_with_sqlite()` |
| KINE-01 | Kinematic Agent queries NGS tracking data fields from PostgreSQL | `make_kinematic_agent(pool)` exists and is tested; never passed to `create_graph_with_sqlite()` |
| KINE-02 | Kinematic Agent produces matchup exploit signals based on geometric mismatches | Blocked by INT-02: `receiver_gsis_id` not in `GraphState`, so every production kinematic query silently uses `""` as the receiver ID |
</phase_requirements>

## Standard Stack

### Core (all already installed — this phase adds no new dependencies)
| Component | Location | Purpose | Status |
|-----------|----------|---------|--------|
| `create_graph_with_sqlite()` | `src/sportsbet/graph/graph.py` line 235 | Production runtime factory — builds graph + wires AsyncSqliteSaver | Exists, missing 4 node params |
| `create_graph()` | `src/sportsbet/graph/graph.py` line 115 | Full graph builder — already accepts all 7 params | Complete, no changes needed |
| `GraphState` TypedDict | `src/sportsbet/graph/state.py` | Shared state passed between nodes | Missing `receiver_gsis_id: str` field |
| `_extract_odds_snapshot()` | `src/sportsbet/graph/agents.py` line 211 | Converts raw Odds API response to `AgentOddsSnapshot` | Inline math must be replaced with `vig.py` calls |
| `american_to_raw_prob` | `src/sportsbet/quant/vig.py` line 19 | Converts American odds int to vig-inclusive Decimal prob | Fully implemented, tested, never imported in prod path |
| `remove_vig_multiplicative` | `src/sportsbet/quant/vig.py` line 45 | Proportional devig — normalizes by overround | Fully implemented, tested, never imported in prod path |
| `make_correlation_guard_node()` | `src/sportsbet/graph/graph.py` line 58 | Factory for CorrelationGuard LangGraph node | Exists, never called from `create_graph_with_sqlite()` |
| `make_aggregator_node()` | `src/sportsbet/graph/graph.py` line 77 | Factory for Aggregator LangGraph node with bankroll/limit params | Exists, never called from `create_graph_with_sqlite()` |
| `make_kinematic_agent()` | `src/sportsbet/graph/agents.py` line 434 | Factory for real kinematic agent bound to asyncpg pool | Exists, never passed in `create_graph_with_sqlite()` |
| `make_arbitrage_agent()` | `src/sportsbet/graph/agents.py` line 268 | Factory for real arbitrage agent | Exists, never passed in `create_graph_with_sqlite()` |

### No new installations required
This phase is entirely internal wiring. `sportsbet.quant.vig`, `sportsbet.arbitrage.correlation_guard`, `sportsbet.arbitrage.aggregator`, and `sportsbet.kinematic` are all already importable within the project.

## Architecture Patterns

### Pattern 1: create_graph_with_sqlite() Extension Pattern

The existing function signature follows a clear additive pattern: each phase that added a new node added a corresponding parameter to `create_graph_with_sqlite()`. Phase 7 continues this pattern for the four remaining nodes.

**Current signature (lines 235–244):**
```python
async def create_graph_with_sqlite(
    db_path: str = ".checkpoints/sportsbet.sqlite",
    pool: Any = None,
    api_key: str | None = None,
    daily_credit_cap: int = 500,
) -> CompiledStateGraph:
```

**Required signature after Phase 7:**
```python
async def create_graph_with_sqlite(
    db_path: str = ".checkpoints/sportsbet.sqlite",
    pool: Any = None,
    api_key: str | None = None,
    daily_credit_cap: int = 500,
    bankroll_usd: float = 10000.0,
    daily_drawdown_limit: float = 0.05,
) -> CompiledStateGraph:
```

The four new nodes are built inside the function body when `pool` is provided (kinematic, arbitrage) or unconditionally (correlation guard, aggregator), mirroring the existing `quant_node` and `context_node` construction pattern.

**Current node construction block (lines 288–302):**
```python
quant_node = None
if pool is not None:
    from sportsbet.graph.agents import make_quant_agent
    quant_node = make_quant_agent(pool)

context_node = None
if pool is not None and api_key is not None:
    from sportsbet.graph.agents import make_context_agent
    context_node = make_context_agent(pool, api_key, daily_credit_cap)

os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
conn = await aiosqlite.connect(db_path)
saver = AsyncSqliteSaver(conn)
return create_graph(checkpointer=saver, quant_node=quant_node, context_node=context_node)
```

**Required node construction block after Phase 7:**
```python
quant_node = None
if pool is not None:
    from sportsbet.graph.agents import make_quant_agent
    quant_node = make_quant_agent(pool)

context_node = None
if pool is not None and api_key is not None:
    from sportsbet.graph.agents import make_context_agent
    context_node = make_context_agent(pool, api_key, daily_credit_cap)

arbitrage_node = None
if pool is not None:
    from sportsbet.graph.agents import make_arbitrage_agent
    arbitrage_node = make_arbitrage_agent()

kinematic_node = None
if pool is not None:
    from sportsbet.graph.agents import make_kinematic_agent
    kinematic_node = make_kinematic_agent(pool)

correlation_guard_node = make_correlation_guard_node()
aggregator_node = make_aggregator_node(bankroll_usd=bankroll_usd, daily_drawdown_limit=daily_drawdown_limit)

os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
conn = await aiosqlite.connect(db_path)
saver = AsyncSqliteSaver(conn)
return create_graph(
    checkpointer=saver,
    quant_node=quant_node,
    context_node=context_node,
    arbitrage_node=arbitrage_node,
    correlation_guard_node=correlation_guard_node,
    aggregator_node=aggregator_node,
    kinematic_node=kinematic_node,
)
```

Note: `correlation_guard_node` and `aggregator_node` are always constructed (they have no pool dependency). The `CorrelationGuard` is stateless; the `Aggregator` persists state across invocations — this is intentional (models the daily gate across multiple `ainvoke` calls).

### Pattern 2: GraphState Field Addition

The project pattern for adding fields to GraphState (established in Phase 4 for `context_signals` and Phase 6 for `kinematic_result`) is:
1. Add the field declaration to the TypedDict body
2. Update the module docstring
3. No import changes needed since `receiver_gsis_id` is a plain `str`

**Current GraphState fields (state.py lines 80–96):** 16 fields, ending with `kinematic_result`.

**Addition required:**
```python
receiver_gsis_id: str  # GSIS player ID for Kinematic Agent matchup queries (Phase 7)
```

The `make_kinematic_agent` closure already reads `state.get("receiver_gsis_id", "")` at line 466 of agents.py. Once the field is declared, callers must include it in their initial state dict. The fallback `""` default remains valid for invocations that do not target a specific receiver (the kinematic agent returns `None` for empty GSIS ID queries due to zero NGS rows matching).

**Important:** The existing `test_graph.py::make_minimal_state()` helper and `test_arbitrage.py::_base_state()` helper do NOT include `receiver_gsis_id`. After adding the field to GraphState, these helpers need to add `"receiver_gsis_id": ""` for type-correctness, though LangGraph tolerates missing TypedDict fields at runtime (it uses dict access).

### Pattern 3: Vig Removal Integration in _extract_odds_snapshot()

The current inline math in `_extract_odds_snapshot()` (agents.py lines 249–259):
```python
# American odds -> implied probability (includes vig; devig in Phase 5)
if price < 0:
    raw_prob = abs(price) / (abs(price) + 100)
else:
    raw_prob = 100 / (price + 100)

return AgentOddsSnapshot(
    ...
    implied_probability=Decimal(str(round(raw_prob, 6))),
    ...
)
```

The comment "devig in Phase 5" was the original intent — Phase 7 fulfills it.

The h2h market always has exactly two outcomes (home win, away win). The vig-correct flow requires both raw probabilities so the overround can be calculated:

```python
# Source: sportsbet/quant/vig.py — american_to_raw_prob + remove_vig_multiplicative
from sportsbet.quant.vig import american_to_raw_prob, remove_vig_multiplicative

outcomes = h2h.get("outcomes", [])
if len(outcomes) < 2:
    return None

prices = [o.get("price", 0) for o in outcomes]
if any(p == 0 for p in prices):
    return None

raw_probs = [american_to_raw_prob(p) for p in prices]

try:
    fair_probs = remove_vig_multiplicative(raw_probs)
except ValueError:
    # Both-positive-odds market (overround < 1) — fall back to raw prob for first outcome
    fair_probs = raw_probs

implied_probability = fair_probs[0]  # probability for outcomes[0] (home team)

return AgentOddsSnapshot(
    game_id=game_id,
    sportsbook=bookmaker.get("key", "unknown"),
    market_type="h2h",
    implied_probability=implied_probability,  # already Decimal from vig.py
    snapped_at=datetime.now(timezone.utc),
)
```

**Critical detail:** `remove_vig_multiplicative` requires at least 2 probs and raises `ValueError` when overround <= 1. The `ValueError` guard is necessary because The Odds API occasionally returns markets with both-positive odds in underdog-heavy matchups.

**Critical detail:** `american_to_raw_prob` returns `Decimal` directly — no `Decimal(str(round(...)))` wrapping needed. This is cleaner than the current code and eliminates a rounding step.

**Current code has a guard `if len(outcomes) == 0: return None`** but does not guard against `len(outcomes) == 1`. The refactored version must guard `len(outcomes) < 2`.

### Recommended Project Structure (unchanged)
```
src/sportsbet/
├── graph/
│   ├── graph.py       # EDIT: create_graph_with_sqlite() extension
│   ├── state.py       # EDIT: add receiver_gsis_id field
│   └── agents.py      # EDIT: _extract_odds_snapshot() vig integration
├── quant/
│   └── vig.py         # READ-ONLY: already complete
├── arbitrage/
│   ├── correlation_guard.py  # READ-ONLY: already complete
│   └── aggregator.py         # READ-ONLY: already complete
└── kinematic/
    └── ...                   # READ-ONLY: already complete
```

### Anti-Patterns to Avoid
- **Restructuring create_graph():** The lower-level `create_graph()` function already accepts all 7 node params and is correct. Only `create_graph_with_sqlite()` needs changes. Do not refactor `create_graph()`.
- **Adding bankroll to GraphState:** `bankroll_usd` and `max_kelly_fraction` are in `Settings` by locked Phase 2 decision. They remain in Settings, not GraphState. Pass them as parameters to `create_graph_with_sqlite()`.
- **Making correlation_guard/aggregator pool-conditional:** These nodes have no DB dependency. They should be constructed unconditionally (always wired), unlike `kinematic_node` and `arbitrage_node` which require a pool.
- **Using AsyncMock for pool.acquire():** Established Phase 4 decision. Use `MagicMock` (not `AsyncMock`) for `pool.acquire` in tests — `AsyncMock` makes `acquire()` return a coroutine which breaks `async with pool.acquire() as conn`.
- **Wrapping vig.py Decimal output in Decimal(str(round(...))):** `american_to_raw_prob` already returns `Decimal` built from strings. Double-wrapping adds unnecessary rounding. Assign the output directly.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| American odds to fair probability | Custom inline division | `american_to_raw_prob` + `remove_vig_multiplicative` from `sportsbet.quant.vig` | Handles both negative and positive odds, uses Decimal throughout, already tested with 9 unit tests |
| Overround normalization | Manual sum and divide | `remove_vig_multiplicative` | Handles residual correction for exact Decimal('1') sum, raises ValueError on invalid markets |
| LangGraph node wrapping for risk controls | Custom orchestration layer | `make_correlation_guard_node()` and `make_aggregator_node()` already in `graph.py` | Already implemented in Phase 5 Plan 03 |

**Key insight:** Every component for Phase 7 was built in earlier phases — the only work is connecting them through `create_graph_with_sqlite()`, one TypedDict field, and one function body change.

## Common Pitfalls

### Pitfall 1: Single-Outcome h2h Guard Missing
**What goes wrong:** `_extract_odds_snapshot()` currently only checks `if not outcomes: return None`. With the new two-outcome requirement for devig, a market with exactly 1 outcome would cause `remove_vig_multiplicative([p])` to raise `ValueError` (overround < 1 since a single probability can't sum > 1 as an overround).
**Why it happens:** The Odds API can return a single-outcome result in malformed or push scenarios.
**How to avoid:** Guard `if len(outcomes) < 2: return None` before calling `american_to_raw_prob`.
**Warning signs:** `ValueError: Invalid market: overround ... <= 1` in logs.

### Pitfall 2: Test State Helpers Missing receiver_gsis_id
**What goes wrong:** `make_minimal_state()` in `test_graph.py` (line 22–38) and `_base_state()` in `test_arbitrage.py` (line 504–526) do not include `receiver_gsis_id`. Adding it to `GraphState` TypedDict doesn't break runtime (LangGraph uses dict access, not TypedDict enforcement), but mypy/pyright will flag test helpers as incomplete.
**Why it happens:** The field is new to GraphState; existing helpers were written before Phase 7.
**How to avoid:** Add `"receiver_gsis_id": ""` to both helper dicts as part of the Phase 7 plan.
**Warning signs:** mypy `TypedDict` missing-key errors in test files.

### Pitfall 3: EV Value Changes After Devig
**What goes wrong:** Any test asserting a specific `ev_percentage` value based on a hardcoded `implied_probability` will fail if the implied_probability is now computed via devig instead of raw division.
**Why it happens:** `remove_vig_multiplicative` on a symmetric -110/-110 market gives `implied_probability = Decimal("0.5")` while raw division gives `Decimal("0.523809...")`.
**How to avoid:** Phase 7 smoke tests should assert `implied_probability` is within expected devigged range, not equal to raw division result. The existing `test_arbitrage.py` integration tests pre-inject `implied_probability` directly into state — they bypass `_extract_odds_snapshot()` entirely and are unaffected. Only tests that call `_extract_odds_snapshot()` directly or via `make_context_agent` need updating.
**Warning signs:** Existing `test_vig.py::test_multiplicative_sums_to_one` confirms -110/-110 devigged = 0.5 exactly; any test expecting 0.523 is wrong post-devig.

### Pitfall 4: Aggregator Instance Lifetime in Tests
**What goes wrong:** The `Aggregator` instance in `make_aggregator_node()` persists `cumulative_exposure_usd` across `ainvoke` calls on the same graph. If a test reuses the same graph object across multiple invocations, the cumulative state bleeds between test scenarios.
**Why it happens:** Phase 5 intentional decision — the Aggregator simulates a daily gate within a process lifetime. But in tests, each scenario needs a fresh gate.
**How to avoid:** Each smoke test must create a new `make_aggregator_node()` call to get a fresh `Aggregator` instance with zero cumulative exposure. Use `MemorySaver()` per test (already established pattern in `conftest.py`).
**Warning signs:** Test that expects `cleared_signals=[signal]` returns `cleared_signals=[]` because a prior test already exhausted the daily limit.

### Pitfall 5: arbitrage_analysis Key in Conditional Edges (Dead Entry)
**What goes wrong:** The audit noted that `"arbitrage_analysis"` in the `conditional_edges` dict (graph.py line 207) is a dead entry — `route_from_master` returns `"arbitrage_agent"` for `request_type="arbitrage_analysis"`, not `"arbitrage_analysis"`. The dead key is harmless but misleading.
**Why it happens:** Phase 5 decision: `route_from_master` was updated to return the node name directly. The mapping entry is redundant.
**How to avoid:** Do not add more dead entries. The Phase 7 smoke test should use `request_type="arbitrage_analysis"` and verify it routes to `arbitrage_agent` (which it will — via the `"arbitrage_agent"` key).

## Code Examples

Verified patterns from existing codebase:

### Calling vig.py from agents.py (new import pattern)
```python
# Source: src/sportsbet/quant/vig.py (lines 19, 45)
# Place import inside _extract_odds_snapshot() to match existing lazy-import pattern
from sportsbet.quant.vig import american_to_raw_prob, remove_vig_multiplicative

raw_probs = [american_to_raw_prob(price) for price in prices]
fair_probs = remove_vig_multiplicative(raw_probs)
# fair_probs[0] is Decimal, assignable directly to AgentOddsSnapshot.implied_probability
```

### Extending create_graph_with_sqlite() — arbitrage_node construction
```python
# Source: matching pattern from quant_node construction (graph.py lines 288–291)
arbitrage_node = None
if pool is not None:
    from sportsbet.graph.agents import make_arbitrage_agent
    arbitrage_node = make_arbitrage_agent()
```

### Extending create_graph_with_sqlite() — unconditional risk control nodes
```python
# Source: make_correlation_guard_node() and make_aggregator_node() already in graph.py (lines 58, 77)
# No pool dependency — always constructed when create_graph_with_sqlite() is called
correlation_guard_node = make_correlation_guard_node()
aggregator_node = make_aggregator_node(
    bankroll_usd=bankroll_usd,
    daily_drawdown_limit=daily_drawdown_limit,
)
```

### GraphState field addition pattern
```python
# Source: state.py — matching Phase 6 kinematic_result addition pattern (line 96)
# Add after kinematic_result:
receiver_gsis_id: str  # GSIS player ID for Kinematic Agent (Phase 7)
```

### Smoke test pattern for create_graph_with_sqlite() node reachability
```python
# Source: test_arbitrage.py lines 566–611 (test_e2e_pipeline pattern)
# Adapted for smoke test — use create_graph_with_sqlite via mock pool
import asyncio, uuid
from unittest.mock import MagicMock
from langgraph.checkpoint.memory import MemorySaver

# For the smoke test, use create_graph() directly with all nodes wired
# (create_graph_with_sqlite uses disk I/O — avoid in tests per established pattern)
from sportsbet.graph.graph import (
    create_graph, make_correlation_guard_node, make_aggregator_node
)
from sportsbet.graph.agents import make_arbitrage_agent, make_kinematic_agent

pool = MagicMock()  # presence triggers node construction path
# ... build mock state with request_type="arbitrage_analysis"
# ... verify all 4 nodes reachable
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Inline American-odds math in `_extract_odds_snapshot()` | `american_to_raw_prob` + `remove_vig_multiplicative` from `vig.py` | Phase 7 (this phase) | EV math becomes mathematically correct; implied_probability no longer overstates sportsbook edge |
| `create_graph_with_sqlite()` wires quant_node + context_node only | All 6 real nodes wired | Phase 7 | Production invocations use real risk controls and kinematic agent |
| `receiver_gsis_id` read via `state.get("receiver_gsis_id", "")` with no TypedDict backing | Declared `receiver_gsis_id: str` in GraphState | Phase 7 | Real receiver lookups produce NGS data; empty-string silent failure eliminated |

**Tech debt this phase closes:**
- INT-01 (HIGH): `create_graph_with_sqlite()` missing Phase 5/6 node wiring
- INT-02 (HIGH): `receiver_gsis_id` not declared in GraphState
- INT-04 (HIGH): Vig removal functions never imported by production pipeline

## Open Questions

1. **Vig method choice: multiplicative vs. power**
   - What we know: `remove_vig_multiplicative` is simpler and correct for standard markets. `remove_vig_power` corrects favorite-longshot bias but is computationally heavier (60-iteration binary search).
   - What's unclear: Whether Phase 7 should make the method configurable (e.g., a `devig_method: str` parameter on `create_graph_with_sqlite()`) or just use multiplicative as the default.
   - Recommendation: Use `remove_vig_multiplicative` as the default for Phase 7. The audit gap only requires that vig removal be connected at all (INT-04). Power devig can be a config option in Phase 8 if needed. Keeps the phase scope minimal.

2. **receiver_gsis_id initialization in existing test helpers**
   - What we know: `make_minimal_state()` (test_graph.py) and `_base_state()` (test_arbitrage.py) and `make_checkpoint_state()` (test_graph.py) do not include `receiver_gsis_id`.
   - What's unclear: Whether to update all existing helpers or rely on LangGraph's runtime dict-access tolerance.
   - Recommendation: Update all three helpers to include `"receiver_gsis_id": ""`. This keeps the test suite type-correct and prevents future mypy failures. The change is mechanical and low-risk.

3. **Aggregator bankroll source in production**
   - What we know: `Settings.bankroll_usd` and `Settings.max_kelly_fraction` are the canonical bankroll params. `create_graph_with_sqlite()` should read from Settings rather than requiring callers to always pass bankroll manually.
   - What's unclear: Whether `create_graph_with_sqlite()` should accept explicit params (more testable) or read from `settings` internally (simpler API).
   - Recommendation: Accept `bankroll_usd` and `daily_drawdown_limit` as params with defaults drawn from `settings`. This is consistent with how `daily_credit_cap` works for the context agent.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pyproject.toml) |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_graph.py tests/test_arbitrage.py tests/test_kinematic.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QUANT-02 | `_extract_odds_snapshot()` returns devigged probability, not raw division result | unit | `pytest tests/test_graph.py -k "test_extract_odds_devigged" -x` | Wave 0 |
| ARBT-01 | `create_graph_with_sqlite()` wires real arbitrage node — EV math uses devigged implied_probability | smoke | `pytest tests/test_graph.py -k "test_create_graph_with_sqlite_nodes" -x` | Wave 0 |
| ARBT-03 | `create_graph_with_sqlite()` wires correlation_guard_node — reachable via arbitrage pipeline | smoke | `pytest tests/test_graph.py -k "test_create_graph_with_sqlite_nodes" -x` | Wave 0 |
| ARBT-04 | `create_graph_with_sqlite()` wires aggregator_node — reachable via arbitrage pipeline | smoke | `pytest tests/test_graph.py -k "test_create_graph_with_sqlite_nodes" -x` | Wave 0 |
| KINE-01 | `create_graph_with_sqlite()` wires kinematic_node when pool provided | smoke | `pytest tests/test_graph.py -k "test_create_graph_with_sqlite_nodes" -x` | Wave 0 |
| KINE-02 | `receiver_gsis_id` declared in GraphState — kinematic invocation uses real GSIS ID | unit | `pytest tests/test_graph.py -k "test_graphstate_has_receiver_gsis_id" -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_graph.py tests/test_arbitrage.py tests/test_vig.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_graph.py` — add `test_graphstate_has_receiver_gsis_id` (asserts `"receiver_gsis_id"` in `get_type_hints(GraphState)`)
- [ ] `tests/test_graph.py` — add `test_extract_odds_devigged` (asserts devigged prob != raw division result for -110 American odds)
- [ ] `tests/test_graph.py` — add `test_create_graph_with_sqlite_nodes` (smoke: `create_graph()` with all 7 params confirms arbitrage, guard, aggregator, kinematic nodes reachable; uses `MemorySaver()` not disk to match test isolation pattern)
- [ ] Update `make_minimal_state()`, `_base_state()`, and `make_checkpoint_state()` in existing test files to include `"receiver_gsis_id": ""`

Note: The smoke test for `create_graph_with_sqlite()` node reachability should use `create_graph()` directly (matching the established test pattern — `create_graph_with_sqlite()` is excluded from tests per existing docstring to avoid disk I/O). The test proves all 4 nodes are wired by invoking the graph with each relevant `request_type`.

## Sources

### Primary (HIGH confidence)
- `src/sportsbet/graph/graph.py` — exact current signatures and node construction pattern
- `src/sportsbet/graph/state.py` — exact current TypedDict fields
- `src/sportsbet/graph/agents.py` lines 211–261 — exact `_extract_odds_snapshot()` implementation
- `src/sportsbet/quant/vig.py` — exact function signatures, Decimal contract, ValueError behavior
- `.planning/v1.0-MILESTONE-AUDIT.md` — authoritative gap list with exact file references
- `tests/test_arbitrage.py` — established integration test patterns for graph wiring tests
- `tests/test_graph.py` — state helper patterns, existing `GraphState` test patterns

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` Decisions section — locked project decisions (bankroll in Settings, import patterns, MagicMock vs AsyncMock)
- `.planning/ROADMAP.md` Phase 7 section — success criteria directly inform test requirements

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all components exist in codebase, no external dependencies
- Architecture: HIGH — three surgical edits to existing files, patterns established by Phases 3–6
- Pitfalls: HIGH — INT-01/02/04 are precisely documented in audit; all edge cases verified in source code

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable codebase — all components already implemented)
