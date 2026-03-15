# Phase 5: Arbitrage, Kelly, and Risk Controls - Research

**Researched:** 2026-03-14
**Domain:** Kelly Criterion sizing, EV calculation, LangGraph node orchestration, correlation guard, daily drawdown gate, full pipeline integration
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ARBT-01 | Arbitrage Agent flags +EV discrepancies by comparing QuantResult true probability against sportsbook implied probability, outputting raw EV percentage and a 3-bullet Trade Plan thesis | EVSignal Pydantic model already defined in models.py with ev_percentage, true_probability, implied_probability, trade_plan (max 3 bullets). Arbitrage node is a stub — real comparison logic needed |
| ARBT-02 | System calculates fractional Kelly Criterion bet sizing based on edge and bankroll parameters — no flat bet sizes are ever output | kelly_fraction field in EVSignal is already capped at Decimal 0.25 by Pydantic Field constraint. Kelly formula is deterministic: f* = (b*p - q) / b. Fractional Kelly = f* * fraction_multiplier. Settings.bankroll_usd and Settings.max_kelly_fraction already exist |
| ARBT-03 | CorrelationGuard node enforces hardcoded stops on conflicting market exposures (e.g., Over passing yards + Under total points) before any signal is output | New LangGraph node needed. Must run before recommendations are emitted. Conflict detection is a set-intersection check on market_type tags |
| ARBT-04 | Aggregator node enforces a daily drawdown gate — if cumulative recommended exposure exceeds the configured limit, no further signals are produced that day | New LangGraph node needed. Must track cumulative exposure (sum of kelly_fraction * bankroll_usd) across graph invocations. Requires state that persists across invocations — either GraphState field or external store |
</phase_requirements>

---

## Summary

Phase 5 is the mathematical core of the output pipeline. It takes the data produced by Phases 3 and 4 — a `QuantResult` (true probability + CI) and an `AgentOddsSnapshot` (sportsbook implied probability, already de-vigged by the time it reaches the arbitrage node) — and converts them into an `EVSignal` with a fractional Kelly stake size and a 3-bullet Trade Plan. Two risk control nodes (CorrelationGuard and Aggregator/DrawdownGate) sit between the Arbitrage Agent and the final output to enforce the prop-firm constraints from CLAUDE.md.

The EV formula is simple: `ev = (true_prob * payout_multiplier) - 1`. The Kelly formula is equally simple: `f* = (b * p - q) / b` where `b = payout_multiplier - 1`, `p = true_probability`, `q = 1 - p`. The complexity is in the guard nodes, the pipeline wiring, and the integration test that chains all four agents end-to-end against the Phase 1 database. Everything builds on existing patterns: the closure-factory pattern from Phase 3, the partial-state-dict update pattern from all prior phases, and the Pydantic strict-mode models already defined in `models.py`.

The key architectural decision for ARBT-04 (drawdown gate) is whether cumulative exposure state is held in memory (module-level dict, reset on process restart) or persisted to PostgreSQL. For v1 single-user local use, a module-level counter gated by a UTC date is sufficient and matches the Phase 4 precedent for the in-memory `_credits_remaining` counter. This is documented as a known limitation (same pattern as CTXT-01 budget tracking).

**Primary recommendation:** Implement the Arbitrage Agent, CorrelationGuard, and Aggregator as a sequential chain in the LangGraph graph. The Arbitrage Agent uses the `make_arbitrage_agent(pool, settings)` closure pattern. CorrelationGuard and Aggregator are pure-function nodes (no I/O) that inspect and mutate `ev_signals` in GraphState. The graph topology changes from single-agent dispatch to a sequential sub-pipeline for `odds_check` requests: `context_agent -> quant_agent -> arbitrage_agent -> correlation_guard -> aggregator -> END`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic v2 | >=2.7 (already installed) | EVSignal, ArbitrageSignal models; strict typing of all outputs | Non-negotiable per CLAUDE.md; ConfigDict strict=True on all models |
| asyncpg | >=0.29 (already installed) | Hot-path async DB reads in arbitrage agent | Pool already created; quant agent uses same pool pattern |
| structlog | >=24.1 (already installed) | Structured log output for every guard decision | Consistent with all prior phases; required for audit trail |
| langgraph | >=0.2 (already installed) | CorrelationGuard and Aggregator as new graph nodes | All agent nodes use LangGraph; no reason to bypass |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| decimal (stdlib) | stdlib | All probability and Kelly fraction arithmetic | Never use float for financial math — all Decimal, always constructed from str |
| datetime (stdlib) | stdlib | UTC date comparison for drawdown gate reset | `datetime.now(timezone.utc).date()` for daily reset check |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Module-level drawdown counter | PostgreSQL `daily_exposure` table | DB is durable across restarts; module-level is simpler, matches Phase 4 precedent for v1 |
| Frozenset conflict detection | LLM-based conflict detection | LLM cannot be used for safety-critical stops (CLAUDE.md); frozenset is O(1) and deterministic |
| Sequential pipeline for odds_check | Parallel sub-graph | Sequential is simpler; EV calculation depends on quant output; parallelism buys nothing here |

**Installation:** No new dependencies. All required libraries are already in `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure

```
src/sportsbet/
├── graph/
│   ├── agents.py         # EXTEND: make_arbitrage_agent closure; real EV+Kelly logic
│   ├── graph.py          # EXTEND: correlation_guard and aggregator nodes added; odds_check
│   │                     #         route becomes a 3-node sequential sub-pipeline
│   ├── models.py         # EXTEND: ArbitrageSignal if needed (or reuse EVSignal)
│   └── state.py          # EXTEND: ev_signals list field; daily_exposure_usd field
├── quant/
│   └── kelly.py          # NEW: kelly_fraction() pure function + ev_percentage() pure function
└── risk/
    └── guards.py         # NEW: CorrelationGuard logic + DrawdownGate logic (pure functions)
tests/
└── test_arbitrage.py     # NEW: all ARBT-01 through ARBT-04 tests
```

### Pattern 1: EV and Kelly Pure Functions

**What:** Two standalone pure functions in `src/sportsbet/quant/kelly.py`. No I/O. No state. Fully unit-testable in isolation. Accept and return `Decimal`.

**When to use:** Called inside `make_arbitrage_agent` after QuantResult and AgentOddsSnapshot are both available from state.

**Mathematical formulas (verified from standard Kelly literature):**

EV percentage (edge over implied probability):
```
ev_pct = true_probability - implied_probability
```
Note: this is the fractional edge expressed as a percentage (e.g., `Decimal("0.07")` = 7% edge). Some implementations express it as `(true_prob * payout) - 1` — both are mathematically equivalent for binary markets. The simpler form `true_prob - implied_prob` maps directly to the EVSignal model's semantic (edge over the market price) and is easier to audit.

Fractional Kelly:
```
# Full Kelly: f* = (b * p - q) / b
# where b = payout_multiplier - 1, p = true_probability, q = 1 - p
# Fractional Kelly: apply a multiplier < 1.0 to reduce variance
# Capped at max_kelly_fraction (0.25) per CLAUDE.md prop firm rule
```

```python
# Source: codebase-verified (EVSignal model in models.py; Kelly formula standard)
from decimal import Decimal

def ev_percentage(true_prob: Decimal, implied_prob: Decimal) -> Decimal:
    """Return fractional EV edge: true_prob - implied_prob.

    Positive value = genuine +EV opportunity.
    Negative value = -EV, must NOT generate an EVSignal (caller guards).
    """
    return true_prob - implied_prob


def kelly_fraction(
    true_prob: Decimal,
    payout_multiplier: Decimal,
    fraction_multiplier: Decimal = Decimal("0.5"),
    max_fraction: Decimal = Decimal("0.25"),
) -> Decimal:
    """Return fractional Kelly stake as a fraction of bankroll.

    Args:
        true_prob: Quant Agent's fair probability estimate.
        payout_multiplier: Decimal odds payout (e.g., Decimal("1.909") for -110).
        fraction_multiplier: Fractional Kelly multiplier (0.5 = half-Kelly).
        max_fraction: Hard cap per CLAUDE.md (0.25 = 25% of bankroll maximum).

    Returns:
        Decimal stake fraction in (0, max_fraction]. Returns Decimal("0") if
        the formula produces a negative value (i.e., -EV situation).

    Notes:
        - Decimal arithmetic throughout; never float.
        - q = 1 - true_prob; b = payout_multiplier - 1
        - f* = (b * p - q) / b
        - Return min(f* * fraction_multiplier, max_fraction)
    """
    b = payout_multiplier - Decimal("1")
    p = true_prob
    q = Decimal("1") - p
    if b <= Decimal("0"):
        return Decimal("0")
    full_kelly = (b * p - q) / b
    if full_kelly <= Decimal("0"):
        return Decimal("0")
    fractional = full_kelly * fraction_multiplier
    return min(fractional, max_fraction)
```

### Pattern 2: Arbitrage Agent Closure Factory (ARBT-01, ARBT-02)

**What:** Same `make_arbitrage_agent(pool, settings)` closure-factory pattern established in Phase 3 (`make_quant_agent`) and Phase 4 (`make_context_agent`).

**When to use:** Replaces the stub `arbitrage_agent` in `agents.py` for `odds_check` request types.

**Pipeline inside the closure:**
1. Read `quant_result` from `state` — if `true_probability is None` (insufficient sample), return `{"ev_signal": None}` immediately.
2. Read `context_signals.odds_snapshot` from `state` — if `None` (budget exhausted or stale), return `{"ev_signal": None}`.
3. De-vig the sportsbook implied probability using existing `vig.py` functions (already implemented in Phase 3). The `AgentOddsSnapshot.implied_probability` is the raw (vig-inclusive) probability; pass it through `remove_vig_multiplicative` or `remove_vig_power` to get the fair implied probability.
4. Compute `ev_pct = ev_percentage(true_prob, fair_implied_prob)`. If `ev_pct <= 0`, return `{"ev_signal": None}` (not +EV).
5. Compute `payout_multiplier` from the implied probability: `payout = 1 / fair_implied_prob`.
6. Compute `kf = kelly_fraction(true_prob, payout, settings.max_kelly_fraction * 0.5, settings.max_kelly_fraction)`.
7. Build `trade_plan` as a 3-bullet list explaining the edge (Quant edge, contextual factors from injury_flags, market comparison).
8. Construct and return `EVSignal`. Pydantic strict validation at construction catches any `ev_percentage <= 0` or `kelly_fraction` out of bounds before the signal exits the node.

```python
# Source: codebase patterns (agents.py, models.py)
def make_arbitrage_agent(pool, settings):
    from sportsbet.quant.kelly import ev_percentage, kelly_fraction

    async def arbitrage_agent(state: GraphState) -> dict[str, Any]:
        quant_result = state.get("quant_result")
        context_signals = state.get("context_signals")

        # Guard: insufficient sample or no odds data
        if quant_result is None or quant_result.true_probability is None:
            log.warning("arbitrage_no_quant_result", session_id=state["session_id"])
            return {"ev_signal": None}
        if context_signals is None or context_signals.odds_snapshot is None:
            log.warning("arbitrage_no_odds", session_id=state["session_id"])
            return {"ev_signal": None}

        true_prob = quant_result.true_probability
        raw_implied = context_signals.odds_snapshot.implied_probability
        # De-vig: both sides of market needed for multiplicative devig;
        # for a binary market complement is 1 - raw_implied (home vs away h2h)
        fair_implied = remove_vig_multiplicative([raw_implied, Decimal("1") - raw_implied])[0]

        ev_pct = ev_percentage(true_prob, fair_implied)
        if ev_pct <= Decimal("0"):
            log.info("arbitrage_no_edge", ev_pct=str(ev_pct))
            return {"ev_signal": None}

        payout = Decimal("1") / fair_implied
        kf = kelly_fraction(true_prob, payout, Decimal("0.5"), Decimal(str(settings.max_kelly_fraction)))

        injury_context = list(state.get("injury_flags", {}).items())[:1]
        trade_plan = [
            f"Quant edge: {float(ev_pct)*100:.1f}% over market implied probability",
            f"Market: {context_signals.odds_snapshot.market_type} @ {context_signals.odds_snapshot.sportsbook}",
            f"Injury context: {injury_context[0] if injury_context else 'none flagged'}",
        ]

        signal = EVSignal(
            ev_percentage=ev_pct,
            true_probability=true_prob,
            implied_probability=fair_implied,
            kelly_fraction=kf,
            trade_plan=trade_plan,
            market_type=context_signals.odds_snapshot.market_type,
        )
        return {"ev_signal": signal}

    return arbitrage_agent
```

### Pattern 3: CorrelationGuard Node (ARBT-03)

**What:** A pure-function LangGraph node that inspects the current `ev_signal` against a hardcoded conflict registry. If a conflicting signal pair is detected, it nulls out `ev_signal` and logs the block. No I/O, no DB, no LLM.

**When to use:** Runs after the Arbitrage Agent, before the Aggregator. Placed as a sequential node in the `odds_check` sub-pipeline.

**Conflict detection logic:** A conflict registry maps `market_type` strings to their mutually exclusive counterparts. The canonical example from ARBT-03: `"over_passing_yards"` conflicts with `"under_total_points"`. The check is a `frozenset` lookup — O(1), deterministic, auditable.

**Key design decision:** In v1, only a single `ev_signal` flows through the graph at a time (one signal per `ainvoke` call). ARBT-03's integration test requires checking two conflicting props. This means either:
1. The guard is tested by running two sequential `ainvoke` calls and checking the second is blocked by the first (using session-level state), OR
2. The GraphState is extended to carry an `ev_signals` list (accumulated across invocations), and the guard checks for conflicts within the list.

Option 2 is more robust and directly satisfies the ARBT-03 success criterion ("blocks both signals from reaching output"). Use a `pending_ev_signals: list[EVSignal]` field in `GraphState` with an Annotated list-append reducer.

```python
# Source: codebase patterns (state.py, CLAUDE.md correlation hard-stop rule)
# In risk/guards.py
from frozenset import ...  # stdlib

CONFLICT_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"over_passing_yards", "under_total_points"}),
    frozenset({"over_rushing_yards", "under_total_points"}),
    # Extend as needed; hardcoded per CLAUDE.md "hardcoded validation"
})

def has_conflict(incoming_market: str, existing_markets: list[str]) -> bool:
    """Return True if incoming_market conflicts with any market in existing_markets."""
    for existing in existing_markets:
        pair = frozenset({incoming_market, existing})
        if pair in CONFLICT_PAIRS:
            return True
    return False
```

```python
# In graph/agents.py or graph/graph.py — CorrelationGuard as a node function
def correlation_guard(state: GraphState) -> dict[str, Any]:
    ev_signal = state.get("ev_signal")
    if ev_signal is None:
        return {}  # nothing to check

    existing = [s.market_type for s in state.get("pending_ev_signals", [])]
    if has_conflict(ev_signal.market_type, existing):
        log.warning("correlation_guard_blocked", market=ev_signal.market_type)
        return {"ev_signal": None}  # blocked

    # Signal is clean — append to pending list
    return {"pending_ev_signals": [ev_signal]}  # reducer appends
```

### Pattern 4: Aggregator / Drawdown Gate (ARBT-04)

**What:** A pure-function LangGraph node that tracks cumulative recommended exposure for the current UTC day. If the cumulative `sum(kelly_fraction * bankroll_usd)` across all signals this day exceeds the configured daily drawdown limit, the Aggregator nulls out `ev_signal` and produces no further signals.

**When to use:** Runs last in the `odds_check` sub-pipeline, after CorrelationGuard.

**State approach:** Module-level dict `_daily_exposure: dict[str, Decimal]` keyed by UTC date string. Resets automatically when the date changes. Matches the Phase 4 precedent for `_credits_remaining`. Documented limitation: resets on process restart (acceptable for v1).

**Configuration:** `Settings.bankroll_usd` and `Settings.max_kelly_fraction` already exist. Add `Settings.daily_drawdown_limit_fraction: float = 0.10` (max 10% of bankroll recommended per day) to `config.py`.

```python
# Source: codebase patterns (config.py, Phase 4 budget manager pattern)
# In risk/guards.py
from datetime import date, datetime, timezone
from decimal import Decimal

_daily_exposure: dict[str, Decimal] = {}  # {"2026-03-14": Decimal("500.00")}

def check_and_update_drawdown(
    kelly_fraction: Decimal,
    bankroll_usd: Decimal,
    daily_limit_usd: Decimal,
) -> bool:
    """Return True if this signal can proceed; False if daily limit exceeded.

    Side effect: if True, adds kelly_fraction * bankroll_usd to today's exposure.
    Thread-safe for single-threaded asyncio event loop (no concurrent writes).
    """
    today = datetime.now(timezone.utc).date().isoformat()
    current = _daily_exposure.get(today, Decimal("0"))
    new_exposure = kelly_fraction * bankroll_usd

    if current + new_exposure > daily_limit_usd:
        return False  # gate: do not add, do not emit

    _daily_exposure[today] = current + new_exposure
    return True
```

### Pattern 5: Sequential Sub-Pipeline for odds_check

**What:** The `odds_check` request type currently routes to a single `arbitrage_agent` node and terminates. Phase 5 extends this to a 3-node sequential chain: `arbitrage_agent -> correlation_guard -> aggregator`.

**Graph topology change in `graph.py`:**

```python
# Before (Phase 2-4 stub):
builder.add_edge("arbitrage_agent", END)

# After (Phase 5):
builder.add_node("correlation_guard", correlation_guard)
builder.add_node("aggregator", aggregator)
builder.add_edge("arbitrage_agent", "correlation_guard")
builder.add_edge("correlation_guard", "aggregator")
builder.add_edge("aggregator", END)
```

**Why sequential (not parallel):** The Aggregator must see the post-guard `ev_signal` (which CorrelationGuard may have nulled), so it must run after CorrelationGuard. The Arbitrage Agent must run before CorrelationGuard (it produces `ev_signal`). All three are strictly sequential.

**create_graph() parameter extension:**
```python
def create_graph(
    checkpointer=None,
    quant_node=None,
    context_node=None,
    arbitrage_node=None,   # NEW: real make_arbitrage_agent(pool, settings) or stub
) -> CompiledStateGraph:
```

### Pattern 6: GraphState Extensions

**What:** Two new fields added to `GraphState` in `state.py`:

1. `pending_ev_signals: list[EVSignal]` — list of signals that have passed the CorrelationGuard. Uses an Annotated list-append reducer so multiple ainvoke calls accumulate signals.
2. `daily_exposure_usd: Decimal` — total recommended exposure today (read-only from the aggregator's perspective; the authoritative value lives in the module-level dict for cross-invocation persistence).

**Annotated list-append reducer for pending_ev_signals:**
```python
# Source: codebase pattern (state.py _last_write_wins reducer)
def _append_reducer(a: list, b: list) -> list:
    """Append new signals to existing list — never overwrites prior signals."""
    return list(a or []) + list(b or [])
```

### Anti-Patterns to Avoid

- **Using float for Kelly or EV calculations:** ALL probability and fraction arithmetic must use `Decimal` constructed from `str`. `float(0.62)` != `Decimal("0.62")` in IEEE-754. Pydantic strict=True models will reject raw floats at runtime.
- **Emitting a flat dollar bet size:** `EVSignal` must never contain a field like `recommended_bet_usd`. Only `kelly_fraction` (fraction of bankroll) is output. The frontend translates `kelly_fraction * bankroll_usd` for display only.
- **Running CorrelationGuard after Aggregator:** The guard must run first — a correlated signal that slips through the guard would erroneously consume drawdown budget.
- **Calling `remove_vig_multiplicative` on a single-outcome market:** The function expects at least two probabilities summing to > 1 (overround). For a binary h2h market, always pass `[raw_implied, 1 - raw_implied]` and use the first output.
- **Accessing `state["ev_signal"]` without `state.get("ev_signal")`:** After CorrelationGuard, `ev_signal` may be `None`. Guard nodes must use `.get()` with a None default.
- **Importing from the graph inside pure-function nodes:** CorrelationGuard and Aggregator are pure functions in `risk/guards.py`. They must not import `graph.py` or any agent module (circular import risk and unnecessary coupling).
- **Using LangGraph parallel branches for the sub-pipeline:** Parallel edges in LangGraph cannot guarantee ordering. The sequential edge chain `A -> B -> C -> END` is the correct pattern when outputs depend on prior nodes.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Odds devig | Custom probability normalization | `vig.py` already implemented (Phase 3) | `remove_vig_multiplicative` and `remove_vig_power` already tested; power devig corrects favorite-longshot bias |
| Pydantic output validation | Manual assertion checks | `EVSignal` model with Field constraints | Kelly cap (0.25), ev_percentage > 0, trade_plan max 3 bullets all enforced at model construction |
| Kelly formula | Lookup table or approximation | The exact closed-form formula: `(b*p - q) / b` | Kelly has a proven closed form; no approximation needed |
| Conflict registry | LLM-based conflict detection | Hardcoded `frozenset[frozenset[str]]` | LLM hallucination in safety-critical stops is non-negotiable prohibition per CLAUDE.md |
| Daily exposure tracking | Separate service or Redis | Module-level `dict[str, Decimal]` keyed by UTC date | V1 is single-user local; same pattern as Phase 4 in-memory credit counter |

**Key insight:** The mathematical core (EV, Kelly) is just arithmetic — two pure functions totaling ~20 lines. The complexity budget goes to the guard nodes (correct LangGraph wiring, state accumulation, correct ordering) and the integration test (full pipeline with real DB).

---

## Common Pitfalls

### Pitfall 1: Viggy Implied Probability Passed to Kelly

**What goes wrong:** `AgentOddsSnapshot.implied_probability` is the raw (vig-inclusive) probability, not the fair probability. If passed directly to `ev_percentage()`, the computed edge is understated (market overround inflates the implied probability).

**Why it happens:** The `_extract_odds_snapshot` function in `agents.py` (Phase 4) stores the raw implied probability. The de-vig step is explicitly deferred to "Phase 5" in the code comment: `# American odds -> implied probability (includes vig; devig in Phase 5)`.

**How to avoid:** Inside `make_arbitrage_agent`, always call `remove_vig_multiplicative([raw_implied, 1 - raw_implied])` before computing EV. The first output of the list is the fair home-team probability.

**Warning signs:** EV percentage appears systematically 2-5% lower than expected; Kelly fraction near zero even for strong Quant signals.

### Pitfall 2: kelly_fraction Returns Negative on -EV Input

**What goes wrong:** The Kelly formula `(b*p - q) / b` returns a negative value when `b*p < q` (i.e., -EV situation). If a negative value is passed to `EVSignal.kelly_fraction`, Pydantic raises `ValidationError` (field has `gt=Decimal("0")` constraint).

**Why it happens:** Failing to guard for `ev_pct <= 0` before constructing `EVSignal`.

**How to avoid:** In `make_arbitrage_agent`, always check `ev_pct > 0` before computing Kelly and constructing `EVSignal`. Return `{"ev_signal": None}` immediately on zero or negative edge. Additionally, in `kelly_fraction()` pure function, return `Decimal("0")` (not raise) on negative full Kelly.

**Warning signs:** `pydantic.ValidationError: kelly_fraction must be > 0` appearing in logs during pipeline runs with low-edge signals.

### Pitfall 3: GraphState pending_ev_signals Not Initialized

**What goes wrong:** `CorrelationGuard` calls `state.get("pending_ev_signals", [])` — but if the field is not declared in `GraphState` TypedDict, mypy/pyright will flag it and `get_type_hints()` in tests may fail.

**Why it happens:** Adding a new field to `GraphState` requires updating both the TypedDict definition AND all `make_minimal_state()` test helper functions in `test_graph.py` and `test_arbitrage.py`.

**How to avoid:** Update `GraphState` TypedDict with `pending_ev_signals: list[EVSignal]`. Initialize it to `[]` in the test helper state factories. Use an Annotated list-append reducer.

**Warning signs:** `KeyError: 'pending_ev_signals'` in CorrelationGuard during test runs; mypy strict errors on `state.get("pending_ev_signals")`.

### Pitfall 4: Drawdown Gate Bypassed on Process Restart

**What goes wrong:** The module-level `_daily_exposure` dict resets to `{}` when the process restarts. If the process is restarted multiple times within the same UTC day, the drawdown limit can be exceeded.

**Why it happens:** Same limitation as Phase 4's `_credits_remaining` counter — in-memory only.

**How to avoid:** Document this as a known v1 limitation in the module docstring. If needed, persist the daily exposure to a `risk_state` table or sidecar JSON file (same recommendation as Phase 4 budget persistence). For v1 acceptance tests, this limitation is acceptable.

**Warning signs:** Cumulative exposure exceeding the limit within a single test run (possible if tests don't reset the module-level dict between tests — use `monkeypatch` or module-level reset fixture).

### Pitfall 5: Decimal Arithmetic with Mixed Types

**What goes wrong:** `Decimal("0.62") * 0.5` raises `TypeError: unsupported operand type(s) for *: 'decimal.Decimal' and 'float'`. Python's Decimal does not auto-coerce floats.

**Why it happens:** `Settings.bankroll_usd` and `Settings.max_kelly_fraction` are `float` in `config.py`. When used in Kelly arithmetic, they must be wrapped in `Decimal(str(...))`.

**How to avoid:** Inside `make_arbitrage_agent`, convert settings values at the top of the closure:
```python
bankroll = Decimal(str(settings.bankroll_usd))
max_kf = Decimal(str(settings.max_kelly_fraction))
```
Never pass `settings.max_kelly_fraction` directly to `kelly_fraction()` without this conversion.

**Warning signs:** `TypeError` in Kelly calculation; mypy `--strict` will not catch this at type-check time because `Decimal * float` is a runtime error, not a type error.

### Pitfall 6: Integration Test Missing context_signals in State

**What goes wrong:** The end-to-end integration test chains `Context -> Quant -> Arbitrage -> CorrelationGuard -> Aggregator`. If `context_signals` is `None` in state (budget exhausted or mock not wired), the Arbitrage Agent short-circuits and returns `{"ev_signal": None}` — the test passes vacuously without exercising the EV path.

**Why it happens:** The integration test must mock the Odds API call (to avoid consuming real credits) AND ensure the mock returns a non-stale, non-None odds snapshot that is wired into `context_signals`.

**How to avoid:** In the integration test, inject a pre-built `ContextSignals` with a valid `AgentOddsSnapshot` directly into the initial state rather than running the full context agent. This isolates the Arbitrage+Guard+Aggregator pipeline from the Odds API dependency.

**Warning signs:** Integration test passes with `ev_signal = None` — always assert `ev_signal is not None` to catch vacuous passes.

### Pitfall 7: Trade Plan Generation Calling an LLM

**What goes wrong:** A developer interprets "3-bullet Trade Plan" as a task for an LLM and routes the EVSignal fields through `ChatOpenAI` or similar to "generate" the thesis text.

**Why it happens:** The CLAUDE.md description says the thesis explains "mathematical and contextual logic." This sounds like free-form text generation.

**How to avoid:** The Trade Plan is a TEMPLATE-FILLED string list. The Arbitrage Agent constructs it from deterministic values: EV percentage (a number), market type (a string), and injury flags (from state). No LLM involved. The `trade_plan: list[str]` field in `EVSignal` holds exactly this.

**Warning signs:** Any code that calls an LLM API inside `make_arbitrage_agent`. The number in the trade plan must match `ev_percentage` exactly (it IS the number — not an LLM description of it).

---

## Code Examples

Verified patterns from official sources and codebase analysis:

### EV and Kelly Pure Functions

```python
# Source: codebase models.py (EVSignal field constraints) + standard Kelly literature
# File: src/sportsbet/quant/kelly.py

from decimal import Decimal


def ev_percentage(true_prob: Decimal, implied_prob: Decimal) -> Decimal:
    """Return fractional edge: true_prob - implied_prob (fair, post-devig)."""
    return true_prob - implied_prob


def kelly_fraction(
    true_prob: Decimal,
    payout_multiplier: Decimal,
    fraction_multiplier: Decimal = Decimal("0.5"),
    max_fraction: Decimal = Decimal("0.25"),
) -> Decimal:
    """Return fractional Kelly stake. Returns Decimal('0') on -EV input."""
    b = payout_multiplier - Decimal("1")
    p = true_prob
    q = Decimal("1") - p
    if b <= Decimal("0"):
        return Decimal("0")
    full_kelly = (b * p - q) / b
    if full_kelly <= Decimal("0"):
        return Decimal("0")
    return min(full_kelly * fraction_multiplier, max_fraction)
```

### De-vig Before EV Calculation

```python
# Source: codebase vig.py (already implemented, tested in Phase 3)
# Pattern: binary h2h market (home vs away) — two-sided
from sportsbet.quant.vig import remove_vig_multiplicative

raw_home = context_signals.odds_snapshot.implied_probability  # Decimal, vig-inclusive
raw_away = Decimal("1") - raw_home  # complement for binary market
fair_home, fair_away = remove_vig_multiplicative([raw_home, raw_away])
# fair_home is now the devigged probability for the "home" outcome
```

### EVSignal Construction (Happy Path)

```python
# Source: codebase models.py (EVSignal definition)
from sportsbet.graph.models import EVSignal
from decimal import Decimal

signal = EVSignal(
    ev_percentage=Decimal("0.07"),       # must be > 0 (Field gt=Decimal("0"))
    true_probability=Decimal("0.62"),
    implied_probability=Decimal("0.55"), # fair (post-devig) implied probability
    kelly_fraction=Decimal("0.05"),      # must be in (0, 0.25] (Field constraint)
    trade_plan=[                         # max 3 bullets (Field max_length=3)
        "Quant edge: 7.0% over market implied probability",
        "Market: h2h @ draftkings",
        "Injury context: none flagged",
    ],
    market_type="h2h",
)
```

### Correlation Conflict Registry

```python
# Source: CLAUDE.md hardcoded correlation hard-stop rule
# File: src/sportsbet/risk/guards.py

CONFLICT_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"over_passing_yards", "under_total_points"}),
    frozenset({"over_rushing_yards", "under_total_points"}),
    frozenset({"over_passing_yards", "under_passing_yards"}),  # trivially conflicting
})

def has_conflict(incoming: str, existing: list[str]) -> bool:
    return any(frozenset({incoming, e}) in CONFLICT_PAIRS for e in existing)
```

### Drawdown Gate

```python
# Source: Phase 4 pattern (_credits_remaining module-level counter)
# File: src/sportsbet/risk/guards.py
from datetime import datetime, timezone
from decimal import Decimal

_daily_exposure: dict[str, Decimal] = {}


def check_and_update_drawdown(
    kelly_fraction: Decimal,
    bankroll_usd: Decimal,
    daily_limit_usd: Decimal,
) -> bool:
    """Return True if signal can proceed. Adds to today's exposure if True."""
    today = datetime.now(timezone.utc).date().isoformat()
    current = _daily_exposure.get(today, Decimal("0"))
    increment = kelly_fraction * bankroll_usd
    if current + increment > daily_limit_usd:
        return False
    _daily_exposure[today] = current + increment
    return True


def reset_daily_exposure_for_test() -> None:
    """Test helper: clear the module-level exposure dict between test cases."""
    _daily_exposure.clear()
```

### Settings Extension (ARBT-04)

```python
# Source: codebase config.py (existing Settings class)
# Extension: add daily_drawdown_limit_fraction field

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/sportsbet"
    database_url_async: str = "postgresql+asyncpg://localhost/sportsbet"
    postgres_db: str = "sportsbet"
    log_level: str = "INFO"

    bankroll_usd: float = 10000.0
    max_kelly_fraction: float = 0.25
    daily_drawdown_limit_fraction: float = 0.10  # NEW: 10% of bankroll per day max
```

### GraphState Extensions

```python
# Source: codebase state.py (GraphState TypedDict pattern)
# New fields for Phase 5:

from typing import Annotated
from decimal import Decimal

def _append_reducer(a: list, b: list) -> list:
    """Append-only reducer for accumulated EV signals list."""
    return list(a or []) + list(b or [])

class GraphState(TypedDict):
    # ... existing fields unchanged ...
    pending_ev_signals: Annotated[list, _append_reducer]  # NEW
    daily_exposure_usd: Decimal | None                    # NEW (informational, read from guard)
```

### Integration Test Pattern

```python
# Source: codebase test_graph.py (make_minimal_state pattern)
# File: tests/test_arbitrage.py

from decimal import Decimal
from datetime import datetime, timezone
from sportsbet.graph.models import AgentOddsSnapshot, ContextSignals, QuantResult

def make_arbitrage_state() -> dict:
    """Return a GraphState dict pre-loaded with real Phase 3+4 outputs for integration tests."""
    snapshot = AgentOddsSnapshot(
        game_id="2025_01_KC_LAC",
        sportsbook="draftkings",
        market_type="h2h",
        implied_probability=Decimal("0.5714"),  # -133 American odds (vig-inclusive)
        snapped_at=datetime.now(timezone.utc),
    )
    context = ContextSignals(
        game_id="2025_01_KC_LAC",
        injury_flags={"P. Mahomes": "Questionable"},
        weather_json=None,
        odds_snapshot=snapshot,
        signals_captured_at=datetime.now(timezone.utc),
    )
    quant = QuantResult(
        true_probability=Decimal("0.62"),
        sample_size=150,
        confidence_interval=(Decimal("0.54"), Decimal("0.70")),
        data_source="postgresql",
    )
    return {
        **make_minimal_state(),
        "request_type": "odds_check",
        "quant_result": quant,
        "context_signals": context,
        "pending_ev_signals": [],
        "daily_exposure_usd": None,
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Full Kelly sizing | Fractional Kelly (0.5x or less, capped at 25%) | Standard prop-firm practice since ~2010 | Full Kelly maximizes long-run growth but has catastrophic drawdown risk; fractional Kelly preserves capital |
| Manual conflict checks | Frozenset-based conflict registry | Project standard (CLAUDE.md) | O(1) lookup; deterministic; auditable; no LLM hallucination risk |
| Flat bet recommendation | Kelly-fraction-of-bankroll output | Non-negotiable project requirement | Maintains mathematical edge over bookmaker; scales with bankroll |
| Ad-hoc output strings | Pydantic EVSignal with field constraints | Phase 2 model definition | ev_percentage > 0 and kelly_fraction in (0, 0.25] enforced at model construction, not in guard logic |

**Deprecated/outdated patterns in this context:**
- Recommending bet sizes in absolute USD (e.g., "Bet $200 on KC -130"): Non-negotiable prohibition per CLAUDE.md.
- Using the LLM to generate trade thesis text: All three bullets must be constructed from deterministic values extracted from state.
- Using `float` for Kelly arithmetic: All Decimal, all the time.

---

## Open Questions

1. **De-vig method for non-binary (3-way) markets**
   - What we know: `remove_vig_multiplicative` and `remove_vig_power` handle arbitrary-length probability sequences. NFL h2h is binary; spreads with push outcomes can be 3-way.
   - What's unclear: Whether Phase 5 v1 scope includes spreads/totals or only h2h moneyline.
   - Recommendation: Scope to h2h moneyline for v1 (already the default market fetched in Phase 4). Document the extension point clearly in `make_arbitrage_agent`.

2. **Payout multiplier source**
   - What we know: `AgentOddsSnapshot` only stores `implied_probability` (not the raw American odds). The payout multiplier must be derived as `1 / fair_implied_prob` after devig.
   - What's unclear: For non-standard markets (e.g., Asian handicap), the relationship between implied probability and payout may not be the simple reciprocal.
   - Recommendation: For h2h moneyline (v1 scope), `payout = 1 / fair_implied_prob` is correct. Document this assumption.

3. **pending_ev_signals across multiple ainvoke calls**
   - What we know: The ARBT-03 success criterion says "a CorrelationGuard test with two conflicting props blocks both signals." This implies running two pipeline invocations.
   - What's unclear: Whether `pending_ev_signals` should accumulate across ainvoke calls (via checkpointer state) or be scoped to a single session.
   - Recommendation: Use the LangGraph checkpointer (same thread_id across two ainvoke calls) to accumulate `pending_ev_signals`. The test fixture should use a single `graph_fixture` with consistent thread_id for both invocations. The Annotated list-append reducer handles this automatically when the checkpointer is wired.

4. **daily_drawdown_limit env var naming**
   - What we know: The new `daily_drawdown_limit_fraction` setting follows the pattern of `max_kelly_fraction` in `config.py`.
   - What's unclear: Whether it should be expressed as a fraction of bankroll (e.g., 0.10 = 10%) or as an absolute USD value.
   - Recommendation: Express as a fraction of bankroll (consistent with `max_kelly_fraction`). Compute the absolute limit in the Aggregator node: `limit_usd = Decimal(str(settings.bankroll_usd)) * Decimal(str(settings.daily_drawdown_limit_fraction))`.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2 + pytest-asyncio 0.23 (already installed) |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `pytest tests/test_arbitrage.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ARBT-01 | `make_arbitrage_agent` returns EVSignal with ev_percentage, 3-bullet trade_plan | unit | `pytest tests/test_arbitrage.py::TestArbitrageAgent::test_ev_signal_produced -x` | Wave 0 |
| ARBT-01 | Returns `{"ev_signal": None}` when quant_result.true_probability is None | unit | `pytest tests/test_arbitrage.py::TestArbitrageAgent::test_no_signal_on_insufficient_sample -x` | Wave 0 |
| ARBT-01 | Returns `{"ev_signal": None}` when context_signals.odds_snapshot is None | unit | `pytest tests/test_arbitrage.py::TestArbitrageAgent::test_no_signal_on_missing_odds -x` | Wave 0 |
| ARBT-01 | Returns `{"ev_signal": None}` when ev_pct <= 0 | unit | `pytest tests/test_arbitrage.py::TestArbitrageAgent::test_no_signal_on_negative_ev -x` | Wave 0 |
| ARBT-02 | kelly_fraction is always in (0, 0.25] — never zero, never > 25% | unit | `pytest tests/test_arbitrage.py::TestKelly::test_kelly_fraction_bounds -x` | Wave 0 |
| ARBT-02 | kelly_fraction() returns Decimal("0") on -EV input | unit | `pytest tests/test_arbitrage.py::TestKelly::test_kelly_zero_on_negative_ev -x` | Wave 0 |
| ARBT-02 | kelly_fraction() caps at max_fraction regardless of edge size | unit | `pytest tests/test_arbitrage.py::TestKelly::test_kelly_cap_enforced -x` | Wave 0 |
| ARBT-03 | CorrelationGuard blocks over_passing_yards + under_total_points pair | unit | `pytest tests/test_arbitrage.py::TestCorrelationGuard::test_conflict_blocked -x` | Wave 0 |
| ARBT-03 | CorrelationGuard passes non-conflicting signals through | unit | `pytest tests/test_arbitrage.py::TestCorrelationGuard::test_non_conflict_passes -x` | Wave 0 |
| ARBT-03 | Integration: two conflicting props in graph — both blocked before output | integration | `pytest tests/test_arbitrage.py::TestCorrelationGuard::test_both_blocked_integration -x` | Wave 0 |
| ARBT-04 | Drawdown gate blocks signals after cumulative exposure exceeds limit | unit | `pytest tests/test_arbitrage.py::TestDrawdownGate::test_gate_blocks_at_limit -x` | Wave 0 |
| ARBT-04 | Drawdown gate resets on new UTC day | unit | `pytest tests/test_arbitrage.py::TestDrawdownGate::test_gate_resets_daily -x` | Wave 0 |
| ARBT-04 | Full pipeline: after limit exceeded, Aggregator returns no further signals | integration | `pytest tests/test_arbitrage.py::TestDrawdownGate::test_aggregator_stops_after_limit -x` | Wave 0 |
| ARBT-01-04 | End-to-end: Context -> Quant -> Arbitrage -> Guard -> Aggregator with real DB | integration | `pytest tests/test_arbitrage.py::TestEndToEnd::test_full_pipeline_e2e -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_arbitrage.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_arbitrage.py` — all ARBT-01 through ARBT-04 test stubs (file does not exist)
- [ ] `src/sportsbet/quant/kelly.py` — `ev_percentage()` and `kelly_fraction()` pure functions
- [ ] `src/sportsbet/risk/__init__.py` + `src/sportsbet/risk/guards.py` — CorrelationGuard and DrawdownGate logic
- [ ] `src/sportsbet/graph/state.py` — `pending_ev_signals` and `daily_exposure_usd` fields added to `GraphState`
- [ ] `src/sportsbet/graph/agents.py` — `make_arbitrage_agent(pool, settings)` closure replaces stub
- [ ] `src/sportsbet/graph/graph.py` — `correlation_guard` and `aggregator` nodes added; `odds_check` route extended to 3-node chain; `arbitrage_node` parameter added to `create_graph()`
- [ ] `src/sportsbet/config.py` — `daily_drawdown_limit_fraction: float = 0.10` field added to `Settings`
- [ ] `tests/conftest.py` — `reset_exposure` fixture that calls `reset_daily_exposure_for_test()` between drawdown gate tests

*(No new framework installations required — all dependencies already in `pyproject.toml`.)*

---

## Sources

### Primary (HIGH confidence)

- Codebase: `src/sportsbet/graph/models.py` — EVSignal Pydantic model definition with all field constraints; verified directly from source
- Codebase: `src/sportsbet/graph/agents.py` — Closure factory pattern (make_quant_agent, make_context_agent); Phase 5 placeholder comment `# Phase 5 replaces this with real odds comparison logic`
- Codebase: `src/sportsbet/graph/graph.py` — Current graph topology; `arbitrage_agent -> END` edge that Phase 5 extends
- Codebase: `src/sportsbet/graph/state.py` — GraphState TypedDict with Annotated reducer pattern
- Codebase: `src/sportsbet/quant/vig.py` — `remove_vig_multiplicative` and `remove_vig_power` implementations; verified de-vig functions already tested
- Codebase: `src/sportsbet/config.py` — `bankroll_usd` and `max_kelly_fraction` Settings fields already present
- Codebase: `.planning/STATE.md` — Accumulated decisions including `EVSignal.kelly_fraction hard cap 0.25 enforced at model level`
- Kelly Criterion formula: standard closed-form `(b*p - q) / b` — mathematically verified; no library needed

### Secondary (MEDIUM confidence)

- `.planning/phases/04-context-and-odds-ingestion/04-RESEARCH.md` — Phase 4 pattern documentation; module-level in-memory counter pattern for budget tracking; validates the same approach for drawdown gate

### Tertiary (LOW confidence)

- None — all findings are based on direct codebase inspection or mathematical formulas.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are already installed; no new dependencies
- Architecture (EV/Kelly math): HIGH — standard closed-form formulas; no uncertainty
- Architecture (LangGraph wiring): HIGH — sequential chain pattern verified in existing graph.py
- Architecture (CorrelationGuard): HIGH — frozenset conflict registry is a known pattern; verified against CLAUDE.md requirement
- Architecture (Drawdown gate): HIGH — module-level dict pattern directly mirrors Phase 4 `_credits_remaining`; v1 limitation documented
- Pitfalls: HIGH — all pitfalls derived from direct inspection of existing code (vig.py, models.py, agents.py)

**Research date:** 2026-03-14
**Valid until:** 2026-04-14 (30 days; all findings based on internal codebase, no external API dependencies)
