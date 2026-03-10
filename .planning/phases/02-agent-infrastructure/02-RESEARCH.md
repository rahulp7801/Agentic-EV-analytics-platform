# Phase 2: Agent Infrastructure - Research

**Researched:** 2026-03-10
**Domain:** LangGraph StateGraph, Pydantic v2 I/O models, SqliteSaver checkpointing
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Request Types & Routing**
- 3 request types in v1: `quant_analysis` → Quant Agent, `odds_check` → Arbitrage Agent, `context_update` → Context Agent
- Master Router always routes to exactly one agent per request — no fan-out parallelism in Phase 2
- Graph is invoked via `await graph.ainvoke(...)` — async Python function, not CLI
- Stub agents return hardcoded fixture state (static QuantResult/EVSignal instance) so Phase 3 can develop against a real interface contract immediately

**GraphState Shape**
- `session_id: str` (UUID), `request_type: str`, `created_at: datetime` — for checkpointing replay and log correlation
- `game_id: str`, `season: int`, `week: int`, `home_team: str`, `away_team: str`, `injury_flags: dict[str, str]`, `weather_json: dict | None` — game context fields
- `error: str | None` — agents set this to signal failure; Master Router routes to END if set
- Bankroll params (`bankroll_usd`, `max_kelly_fraction`) live in `Settings` (config.py), NOT in GraphState — prevents mutation mid-graph
- All fields written by multiple agents use `Annotated` reducers (INFRA-01 requirement)

**Pydantic I/O Models**
- **QuantParams**: `game_id: str`, `season: int`, `week: int`, `posteam: str`, `stat_type: Literal['passing', 'rushing', 'receiving']`, `filters: dict[str, Any]`
- **QuantResult**: output of Quant Agent — historical win rates and query results (fields defined by Phase 3, stub returns fixture)
- **EVSignal**: `ev_percentage: Decimal`, `true_probability: Decimal`, `implied_probability: Decimal`, `kelly_fraction: Decimal`, `trade_plan: list[str]` (max 3 items), `market_type: str`
- **AgentOddsSnapshot** (separate from ingestion model): `game_id: str`, `sportsbook: str`, `market_type: str`, `implied_probability: Decimal` (already converted from American odds), `snapped_at: datetime` — agent layer never sees raw American odds
- **GameState**: matches GraphState game context fields — `game_id`, `season`, `week`, `home_team`, `away_team`, `injury_flags`, `weather_json`
- **Validation rules**: range guards only — `kelly_fraction: 0 < x ≤ 0.25`, `ev_percentage: x > 0`, `season: 1999–2030`
- All models: Pydantic v2 with `ConfigDict(strict=True)` — no v1 patterns

**Checkpointing**
- **Backend**: SqliteSaver for runtime, InMemorySaver for tests — avoid AsyncPostgresSaver until API is verified
- **Scope**: checkpoint after every node (LangGraph default behavior — no extra code)
- **Replay**: caller passes `thread_id` to `ainvoke(config={'configurable': {'thread_id': '...'}})` — explicit, no magic
- **Test isolation**: tests inject InMemorySaver with a fresh UUID `thread_id` per test — no disk I/O, no cleanup needed

### Claude's Discretion
- QuantResult field shape (Phase 3 will define what queries return)
- Exact Annotated reducer implementations (standard `operator.add` or custom merge)
- SqliteSaver file path convention (e.g., `.checkpoints/sportsbet.sqlite`)
- Graph compilation and StateGraph builder pattern

### Deferred Ideas (OUT OF SCOPE)
- AsyncPostgresSaver — revisit once LangGraph 0.3.x API is confirmed stable (Phase 4 or later)
- Fan-out parallelism via Send API — deferred to Phase 5 when Arbitrage Agent needs to run concurrently with Quant Agent
- CLI invocation wrapper — deferred to post-v1 ops tooling
- `confidence_score` on EVSignal — deferred to Phase 5 when scoring logic is defined
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | System defines a GraphState TypedDict with explicit Annotated reducers for all fields written by multiple agents — no last-write-wins collisions | LangGraph Annotated reducer pattern verified; `operator.add` for list accumulation, custom reducer for dict merge; TypedDict fields without Annotated default to last-write-wins |
| INFRA-02 | System routes queries through a LangGraph Master Router (supervisor) with conditional edges to specialist sub-agents based on request_type | `add_conditional_edges()` + routing function pattern verified; router returns string key mapping to node name; `error` field check → END is a second conditional path |
| INFRA-03 | System defines all Pydantic I/O models (QuantParams, QuantResult, OddsSnapshot, EVSignal, GameState) before any agent logic is written | Pydantic v2 `ConfigDict(strict=True)` + `@field_validator` pattern verified; `Decimal` field constraints; `Literal` for stat_type; range validators via `@field_validator` |
| INFRA-04 | System persists LangGraph graph state via SqliteSaver checkpointing from Phase 1, enabling replay on failure | `AsyncSqliteSaver.from_conn_string(path)` as async context manager verified; `langgraph-checkpoint-sqlite==3.0.3` import path confirmed; `InMemorySaver` for tests |
</phase_requirements>

---

## Summary

Phase 2 builds the LangGraph graph skeleton that all downstream phases (3-6) code against. The phase produces no business logic — only the wiring, state contracts, and Pydantic I/O models that enforce discipline across agent boundaries. Getting this right is foundational: incorrect GraphState reducers cause silent data loss under concurrency, and I/O models defined loosely here propagate into every agent in later phases.

**Critical version finding:** LangGraph has reached version 1.1.0 (released March 10, 2026) and the checkpoint package is at 4.0.1. The package is no longer in the 0.2.x or 0.3.x range referenced in CONTEXT.md blockers. The import paths have stabilized: `from langgraph.checkpoint.memory import InMemorySaver` (not `MemorySaver`), `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver` for async use. Because `graph.ainvoke()` is async, the project must use `AsyncSqliteSaver`, not the synchronous `SqliteSaver` — using a sync checkpointer with an async graph call hangs silently.

**Key architecture insight:** GraphState fields that are only written by one node need no `Annotated` reducer — last-write-wins is safe and is what LangGraph does by default. Only fields written by multiple nodes require `Annotated[T, reducer]`. For this phase, `error: str | None` and any accumulated output lists are the candidates. All other GraphState fields are written once by the input initialization, so they need no reducer.

**Primary recommendation:** Use `AsyncSqliteSaver.from_conn_string(".checkpoints/sportsbet.sqlite")` as an async context manager in production; use `InMemorySaver()` in tests. Build the StateGraph with `add_conditional_edges` routing on `request_type`, with a second `add_conditional_edges` on `error` field to short-circuit to `END`. All Pydantic models use `ConfigDict(strict=True)` and `@field_validator` — no v1 `@validator` pattern.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `langgraph` | `>=1.1.0` | StateGraph, conditional edges, compiled graph | Project requirement; current stable release as of 2026-03-10 |
| `langgraph-checkpoint` | `4.0.1` | Base checkpointer interface + `InMemorySaver` | Ships with langgraph; `InMemorySaver` is the test-safe checkpointer |
| `langgraph-checkpoint-sqlite` | `3.0.3` | `AsyncSqliteSaver` for persistent async checkpointing | Official LangGraph SQLite backend; separate install required |
| `pydantic` | `>=2.7,<3.0` | I/O model validation with `ConfigDict(strict=True)` | Already in pyproject.toml; non-negotiable per CLAUDE.md |
| `python-ulid` or `uuid` | stdlib `uuid` | UUID generation for `session_id` | stdlib `uuid.uuid4()` is sufficient; no extra dependency needed |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest-asyncio` | `>=0.23` | Async test support for `ainvoke` tests | Already in dev deps; `asyncio_mode = "auto"` already set |
| `structlog` | `>=24.1` | Structured logging in stub nodes | Already in deps; log `request_type` and `session_id` per node entry |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `AsyncSqliteSaver` | `SqliteSaver` | `SqliteSaver` is sync-only — hangs silently when used with `ainvoke`. Do not use. |
| `AsyncSqliteSaver` | `AsyncPostgresSaver` | `AsyncPostgresSaver` requires `langgraph-checkpoint-postgres`; API verified stable but CONTEXT.md defers to Phase 4. |
| `InMemorySaver` (tests) | `AsyncSqliteSaver` with `:memory:` | `InMemorySaver` is simpler, no aiosqlite dependency in tests; preferred for unit/integration tests |
| TypedDict for GraphState | Pydantic BaseModel for GraphState | Pydantic state requires full reconstruction to update one field — breaks LangGraph's partial-update merge pattern. Use TypedDict for state, Pydantic for I/O contracts only. |

**Installation:**

```bash
uv add langgraph langgraph-checkpoint-sqlite
```

Note: `langgraph-checkpoint` (for `InMemorySaver`) ships with `langgraph` — no separate install.

---

## Architecture Patterns

### Recommended Project Structure

```
src/sportsbet/
├── graph/
│   ├── __init__.py          # exports: graph, GraphState
│   ├── state.py             # GraphState TypedDict + reducer definitions
│   ├── models.py            # Pydantic I/O models: QuantParams, QuantResult, EVSignal, AgentOddsSnapshot, GameState
│   ├── router.py            # master_router node + route_request function
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── quant_stub.py    # quant_agent stub node
│   │   ├── arbitrage_stub.py # arbitrage_agent stub node
│   │   └── context_stub.py  # context_agent stub node
│   └── builder.py           # StateGraph wiring + compile() + AsyncSqliteSaver setup
├── config.py                # Settings — add bankroll_usd, max_kelly_fraction here
└── db/
    └── ...                  # Phase 1 assets (unchanged)
tests/
├── conftest.py              # existing + add graph_checkpointer fixture (InMemorySaver)
├── test_graph_state.py      # INFRA-01: reducer tests, concurrent-write simulation
├── test_graph_routing.py    # INFRA-02: conditional edge dispatch tests
├── test_pydantic_models.py  # INFRA-03: model validation + rejection tests
└── test_checkpointing.py    # INFRA-04: SqliteSaver persist + replay tests
```

### Pattern 1: GraphState TypedDict with Annotated Reducers (INFRA-01)

**What:** Fields written by multiple agents use `Annotated[T, reducer]`. Fields written once (initialization) use plain types — last-write-wins is correct and intended.

**When to use:** Any field that more than one node can update must have a reducer. For this phase, `error` is the only field written by multiple agents (any stub can set it). All game context fields are written at initialization only.

**Recommendation for reducers:**
- `error: Annotated[str | None, _first_error]` — custom reducer: keep the first non-None error, don't overwrite with None if error already set
- For future list accumulation fields (Phase 3+): `Annotated[list[T], operator.add]`

**Example:**

```python
# src/sportsbet/graph/state.py
from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any

from typing_extensions import TypedDict


def _first_error(existing: str | None, new: str | None) -> str | None:
    """Reducer: keep the first error written; ignore subsequent None overwrites."""
    if existing is not None:
        return existing
    return new


class GraphState(TypedDict):
    # Identity — written once at invocation, never updated
    session_id: str           # UUID str
    request_type: str         # "quant_analysis" | "odds_check" | "context_update"
    created_at: datetime

    # Game context — written once at invocation, never updated
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    injury_flags: dict[str, str]
    weather_json: dict[str, Any] | None

    # Error propagation — written by any agent; reducer prevents accidental None-overwrite
    error: Annotated[str | None, _first_error]

    # Agent outputs — each written by exactly one agent (no reducer needed)
    # These are plain Optional fields; added Phase 3+ when stub returns real data
    quant_result: dict[str, Any] | None          # Phase 3 will type this as QuantResult
    ev_signal: dict[str, Any] | None             # Phase 5 will type this as EVSignal
    odds_snapshot: dict[str, Any] | None         # Phase 4 will type this as AgentOddsSnapshot
```

**Why TypedDict, not Pydantic for state:** LangGraph merges state via partial dict updates (nodes return only the keys they set). Pydantic BaseModel requires full object reconstruction for any update. TypedDict's partial-update semantics are a design requirement of LangGraph — using Pydantic BaseModel for state breaks this pattern.

### Pattern 2: StateGraph Builder with Conditional Edges (INFRA-02)

**What:** Master Router is a node that reads `request_type` from state and returns a routing key. Two `add_conditional_edges` calls handle routing: one for `request_type` dispatch, one for `error` early-exit.

**When to use:** The routing function runs before any agent. If `error` is already set on input state (defensive check), Master Router routes to `END` immediately.

**Example:**

```python
# src/sportsbet/graph/router.py
from __future__ import annotations

from langgraph.graph import END

from sportsbet.graph.state import GraphState

REQUEST_TYPE_ROUTES = {
    "quant_analysis": "quant_agent",
    "odds_check": "arbitrage_agent",
    "context_update": "context_agent",
}


def master_router(state: GraphState) -> GraphState:
    """Master Router node: validates request_type, short-circuits on error."""
    # No mutation — router only reads state; routing decisions are in route_request
    return {}  # type: ignore[return-value]  # no-op: routing is via conditional edge


def route_request(state: GraphState) -> str:
    """Routing function for conditional edge: maps request_type to agent node name."""
    if state.get("error") is not None:
        return END  # short-circuit: error already set before routing

    request_type = state.get("request_type", "")
    if request_type not in REQUEST_TYPE_ROUTES:
        # Unknown request type — set error (handled by returning special key)
        return "__unknown__"

    return REQUEST_TYPE_ROUTES[request_type]
```

```python
# src/sportsbet/graph/builder.py
from __future__ import annotations

import operator

from langgraph.graph import END, START, StateGraph

from sportsbet.graph.nodes.arbitrage_stub import arbitrage_agent_stub
from sportsbet.graph.nodes.context_stub import context_agent_stub
from sportsbet.graph.nodes.quant_stub import quant_agent_stub
from sportsbet.graph.router import REQUEST_TYPE_ROUTES, master_router, route_request
from sportsbet.graph.state import GraphState


def build_graph() -> StateGraph:
    """Construct and return the compiled LangGraph StateGraph."""
    builder = StateGraph(GraphState)

    # Register nodes
    builder.add_node("master_router", master_router)
    builder.add_node("quant_agent", quant_agent_stub)
    builder.add_node("arbitrage_agent", arbitrage_agent_stub)
    builder.add_node("context_agent", context_agent_stub)

    # Entry edge
    builder.add_edge(START, "master_router")

    # Conditional routing from Master Router → specialist stubs (+ unknown + error)
    route_map = {v: v for v in REQUEST_TYPE_ROUTES.values()}
    route_map[END] = END
    route_map["__unknown__"] = END
    builder.add_conditional_edges("master_router", route_request, route_map)

    # All specialist stubs → END
    builder.add_edge("quant_agent", END)
    builder.add_edge("arbitrage_agent", END)
    builder.add_edge("context_agent", END)

    return builder
```

### Pattern 3: Pydantic v2 I/O Models with ConfigDict(strict=True) (INFRA-03)

**What:** All agent I/O models use Pydantic v2 with `ConfigDict(strict=True)`. Range guards enforced via `@field_validator`. `Decimal` (not `float`) for all probability and monetary fields. `Literal` for enum-like fields.

**When to use:** Every model that crosses an agent boundary — inputs to agents, outputs from agents, and what the frontend will eventually consume.

**Example:**

```python
# src/sportsbet/graph/models.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class QuantParams(BaseModel):
    """Input to the Quant Agent — validated before any SQL is constructed."""

    model_config = ConfigDict(strict=True)

    game_id: str
    season: int
    week: int
    posteam: str
    stat_type: Literal["passing", "rushing", "receiving"]
    filters: dict[str, Any]

    @field_validator("season")
    @classmethod
    def season_in_range(cls, v: int) -> int:
        if not (1999 <= v <= 2030):
            raise ValueError(f"season must be 1999–2030, got {v}")
        return v


class QuantResult(BaseModel):
    """Output of the Quant Agent. Fields to be expanded in Phase 3."""

    model_config = ConfigDict(strict=True)

    game_id: str
    season: int
    # Phase 3 will add: historical_win_rate, sample_size, query_params, raw_rows
    # Stub fixture returns this model with minimal fields to establish the contract


class AgentOddsSnapshot(BaseModel):
    """Odds as seen by the Arbitrage Agent — probability only, no raw American odds."""

    model_config = ConfigDict(strict=True)

    game_id: str
    sportsbook: str
    market_type: str
    implied_probability: Decimal   # pre-converted from American odds; vig-removed
    snapped_at: datetime

    @field_validator("implied_probability")
    @classmethod
    def probability_in_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") < v < Decimal("1")):
            raise ValueError(f"implied_probability must be (0, 1), got {v}")
        return v


class EVSignal(BaseModel):
    """Output of the Arbitrage Agent — the final actionable trade signal."""

    model_config = ConfigDict(strict=True)

    ev_percentage: Decimal
    true_probability: Decimal
    implied_probability: Decimal
    kelly_fraction: Decimal
    trade_plan: list[str]    # max 3 items enforced by validator
    market_type: str

    @field_validator("ev_percentage")
    @classmethod
    def ev_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError(f"ev_percentage must be > 0, got {v}")
        return v

    @field_validator("kelly_fraction")
    @classmethod
    def kelly_in_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") < v <= Decimal("0.25")):
            raise ValueError(f"kelly_fraction must be (0, 0.25], got {v}")
        return v

    @field_validator("trade_plan")
    @classmethod
    def trade_plan_max_three(cls, v: list[str]) -> list[str]:
        if len(v) > 3:
            raise ValueError(f"trade_plan must have ≤ 3 items, got {len(v)}")
        return v


class GameState(BaseModel):
    """Structured game context — mirrors GraphState game context fields."""

    model_config = ConfigDict(strict=True)

    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    injury_flags: dict[str, str]
    weather_json: dict[str, Any] | None

    @field_validator("season")
    @classmethod
    def season_in_range(cls, v: int) -> int:
        if not (1999 <= v <= 2030):
            raise ValueError(f"season must be 1999–2030, got {v}")
        return v
```

### Pattern 4: AsyncSqliteSaver Checkpointing (INFRA-04)

**What:** Use `AsyncSqliteSaver` (not `SqliteSaver`) because the graph is invoked with `ainvoke`. The saver is used as an async context manager in production. Tests use `InMemorySaver` — no disk I/O, no cleanup.

**Critical rule:** Sync `SqliteSaver` + async `ainvoke` hangs silently (confirmed via GitHub issue #1800). Always match: async graph call → async checkpointer.

**Production usage:**

```python
# src/sportsbet/graph/builder.py  (continued)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

CHECKPOINT_PATH = ".checkpoints/sportsbet.sqlite"

async def run_graph(input_state: dict, thread_id: str) -> dict:
    """Invoke the compiled graph with AsyncSqliteSaver checkpointing."""
    builder = build_graph()
    async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_PATH) as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(input_state, config)
    return result
```

**Test usage:**

```python
# tests/conftest.py  (addition to existing)
import pytest
from langgraph.checkpoint.memory import InMemorySaver

@pytest.fixture
def graph_checkpointer() -> InMemorySaver:
    """Fresh InMemorySaver per test — no disk I/O, no state bleed between tests."""
    return InMemorySaver()
```

```python
# tests/test_checkpointing.py
import uuid
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sportsbet.graph.builder import build_graph

@pytest.mark.asyncio
async def test_checkpoint_persists_run(graph_checkpointer: InMemorySaver) -> None:
    builder = build_graph()
    graph = builder.compile(checkpointer=graph_checkpointer)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    input_state = {
        "session_id": thread_id,
        "request_type": "quant_analysis",
        "created_at": datetime.utcnow(),
        "game_id": "2023_01_KC_DET",
        "season": 2023,
        "week": 1,
        "home_team": "DET",
        "away_team": "KC",
        "injury_flags": {},
        "weather_json": None,
        "error": None,
        "quant_result": None,
        "ev_signal": None,
        "odds_snapshot": None,
    }

    result = await graph.ainvoke(input_state, config)
    # Verify state was checkpointed by retrieving it
    state_snapshot = await graph.aget_state(config)
    assert state_snapshot is not None
    assert state_snapshot.values["session_id"] == thread_id
```

### Pattern 5: Stub Agent Pattern

**What:** Stub agents return a hardcoded fixture instance of their output model. They validate the fixture via Pydantic instantiation — this fails immediately if the model contract is broken, giving Phase 3 a real validation point.

**When to use:** All 3 specialist nodes in Phase 2. Never return raw dicts — always return a model-validated fixture.

**Example:**

```python
# src/sportsbet/graph/nodes/quant_stub.py
from __future__ import annotations

import structlog
from sportsbet.graph.models import QuantResult
from sportsbet.graph.state import GraphState

log = structlog.get_logger()

# Fixture: Phase 3 will replace this with real DB query results
_FIXTURE_QUANT_RESULT = QuantResult(
    game_id="2023_01_KC_DET",
    season=2023,
)


def quant_agent_stub(state: GraphState) -> dict:
    """Stub Quant Agent — returns hardcoded QuantResult fixture.

    Phase 3 replaces the fixture with real asyncpg queries.
    The Pydantic model instantiation here validates the contract at test time.
    """
    log.info("quant_agent_stub", session_id=state.get("session_id"), game_id=state.get("game_id"))
    return {
        "quant_result": _FIXTURE_QUANT_RESULT.model_dump(),
    }
```

### Pattern 6: Settings Extension for Bankroll Params

**What:** Add `bankroll_usd` and `max_kelly_fraction` to `sportsbet.config.Settings`. These never touch GraphState — agents read them at call time from `settings`, preventing mid-graph mutation.

**Example:**

```python
# src/sportsbet/config.py  (additions only)
class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/sportsbet"
    database_url_async: str = "postgresql+asyncpg://localhost/sportsbet"
    postgres_db: str = "sportsbet"
    log_level: str = "INFO"

    # Bankroll parameters — read by Arbitrage Agent in Phase 5
    bankroll_usd: float = 10_000.0
    max_kelly_fraction: float = 0.25
```

### Anti-Patterns to Avoid

- **TypedDict fields without Annotated for multi-writer fields:** LangGraph uses last-write-wins by default. If two nodes both write `error`, whichever runs last silently wins. Use `Annotated[str | None, _first_error]` to preserve the first error.
- **Using `SqliteSaver` (sync) with `ainvoke` (async):** The program hangs without raising an exception. This is a known LangGraph issue. Always use `AsyncSqliteSaver` with async graph calls.
- **Pydantic BaseModel as GraphState schema:** LangGraph expects partial dict updates from nodes. Pydantic models require full reconstruction for any update. Use TypedDict for state, Pydantic only for I/O contract models.
- **Putting bankroll params in GraphState:** Any agent could overwrite them mid-graph. They belong in `settings` (immutable at invocation time).
- **Returning full state dict from node:** Nodes must return only the keys they changed. Returning the full state dict means every node write stomps every other node's output.
- **`@validator` or `@root_validator` on Pydantic models:** These are v1 patterns that silently coerce or fail. Use `@field_validator` with `@classmethod` decorator.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| State persistence across invocations | Custom SQLite writer | `AsyncSqliteSaver` | Handles serialization, versioning, thread isolation, and async safety |
| In-memory test checkpoints | Temporary SQLite files | `InMemorySaver` | Zero disk I/O, zero cleanup, guaranteed isolation per test |
| Agent routing logic | if/elif chains in a monolith | `add_conditional_edges` + routing function | LangGraph manages execution order, parallelism, and retry semantics automatically |
| Request type enum validation | `if request_type not in [...]` | `Literal["quant_analysis", "odds_check", "context_update"]` in Pydantic model | Pydantic strict mode rejects unknown values at model instantiation, not at runtime branch |
| Probability range guards | Manual `assert 0 < p < 1` in agent | `@field_validator` on Pydantic model | Raises `ValidationError` before the value reaches any SQL or downstream agent |
| Float for probabilities/kelly | `float` fields | `Decimal` fields | Float representation errors compound in Kelly calculations; `Decimal` is exact |

**Key insight:** LangGraph's checkpointing, routing, and state management are production-hardened. The only custom code needed is: the GraphState TypedDict definition, the reducer functions, the routing function that reads `request_type`, and the Pydantic model validators. Everything else is wiring.

---

## Common Pitfalls

### Pitfall 1: Sync Checkpointer with Async Graph Invocation
**What goes wrong:** `SqliteSaver` used with `await graph.ainvoke(...)` — the process hangs indefinitely with no exception raised.
**Why it happens:** `SqliteSaver` implements synchronous checkpoint methods; async graph execution calls async checkpoint methods that are not implemented.
**How to avoid:** Use `AsyncSqliteSaver` (from `langgraph.checkpoint.sqlite.aio`) when the graph is invoked with `ainvoke`, `astream`, or `abatch`. Use `SqliteSaver` only with `invoke` and `stream`.
**Warning signs:** `await graph.ainvoke(...)` never returns; no exception in logs.

### Pitfall 2: Missing Annotated Reducer Causes Silent Data Loss
**What goes wrong:** Two agents both write to the same GraphState field without a reducer. The second write silently overwrites the first.
**Why it happens:** LangGraph's default merge behavior is last-write-wins for plain TypedDict fields.
**How to avoid:** Audit every GraphState field: if more than one node can write it, it needs `Annotated[T, reducer]`. For this phase, `error` is the primary candidate.
**Warning signs:** Concurrent-write test shows final state has only one agent's value; earlier value is gone.

### Pitfall 3: QuantResult with Undefined Fields Breaks Phase 3 Contract
**What goes wrong:** `QuantResult` defined as an empty model or with vague `dict[str, Any]` fields — Phase 3 agent authors have no contract to code against.
**Why it happens:** "Phase 3 will define this" becomes an excuse to leave QuantResult undefined.
**How to avoid:** Define a minimal QuantResult now with at least `game_id` and `season`. Add a `# Phase 3 expands:` comment documenting what fields will be added. The stub returns a fixture of this model — the Pydantic instantiation in the stub is the contract test.
**Warning signs:** Phase 3 starts by discovering there's no model to extend.

### Pitfall 4: `MemorySaver` Import (Old Name)
**What goes wrong:** `from langgraph.checkpoint.memory import MemorySaver` — class name was `MemorySaver` in older versions.
**Why it happens:** Blog posts and older docs use `MemorySaver`.
**How to avoid:** Use `InMemorySaver` — the current class name as of `langgraph-checkpoint 4.0.1`. Import: `from langgraph.checkpoint.memory import InMemorySaver`.
**Warning signs:** `ImportError: cannot import name 'MemorySaver'`.

### Pitfall 5: Pydantic strict=True Rejects int for Decimal Field
**What goes wrong:** `EVSignal(ev_percentage=5)` raises `ValidationError` because `5` (int) is not `Decimal` in strict mode.
**Why it happens:** `ConfigDict(strict=True)` disables type coercion. Pydantic will not convert `int` or `float` to `Decimal` automatically.
**How to avoid:** Always pass `Decimal("0.05")` when constructing models with Decimal fields. In fixture stubs, use `Decimal` literals explicitly.
**Warning signs:** `ValidationError: Input should be an instance of Decimal`.

### Pitfall 6: Node Returns Full State Dict Instead of Partial Update
**What goes wrong:** A node function returns `return state` (the full dict) instead of `return {"quant_result": ...}` (partial). This causes every key in state to be "written" by this node, defeating reducer logic.
**Why it happens:** Returning the full state dict seems natural coming from non-LangGraph patterns.
**How to avoid:** Nodes must return a dict containing ONLY the keys they modified. All other keys remain at their previous values via LangGraph's merge.
**Warning signs:** `error` field set by a previous node is `None` after the next node runs.

### Pitfall 7: AsyncSqliteSaver File Path on Windows
**What goes wrong:** `.checkpoints/sportsbet.sqlite` fails because the `.checkpoints/` directory does not exist.
**Why it happens:** SQLite does not create intermediate directories.
**How to avoid:** `os.makedirs(".checkpoints", exist_ok=True)` before calling `AsyncSqliteSaver.from_conn_string(...)`.
**Warning signs:** `sqlite3.OperationalError: unable to open database file`.

---

## Code Examples

Verified patterns from official sources:

### StateGraph Build + Compile + InMemorySaver (Test Pattern)

```python
# Source: LangGraph official docs (docs.langchain.com/oss/python/langgraph)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

builder = StateGraph(GraphState)
builder.add_node("master_router", master_router)
builder.add_node("quant_agent", quant_agent_stub)
builder.add_edge(START, "master_router")
builder.add_conditional_edges("master_router", route_request, {
    "quant_agent": "quant_agent",
    END: END,
})
builder.add_edge("quant_agent", END)

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)
config = {"configurable": {"thread_id": "test-thread-1"}}
result = await graph.ainvoke(input_state, config)
```

### AsyncSqliteSaver with Context Manager (Production Pattern)

```python
# Source: langgraph-checkpoint-sqlite 3.0.3 PyPI + official docs
import os
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

os.makedirs(".checkpoints", exist_ok=True)
async with AsyncSqliteSaver.from_conn_string(".checkpoints/sportsbet.sqlite") as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": session_id}}
    result = await graph.ainvoke(input_state, config)
```

### Replay from Checkpoint

```python
# Source: LangGraph persistence docs
# Replay by passing the same thread_id — LangGraph resumes from last checkpoint
config = {"configurable": {"thread_id": existing_session_id}}
result = await graph.ainvoke(None, config)  # None input = resume from checkpoint
```

### Annotated Reducer Definition

```python
# Source: LangGraph graph-api docs
from typing import Annotated
from typing_extensions import TypedDict

def _first_error(existing: str | None, new: str | None) -> str | None:
    """Keep first non-None error; ignore None overwrites."""
    return existing if existing is not None else new

class GraphState(TypedDict):
    error: Annotated[str | None, _first_error]
    # Fields written by exactly one node need no Annotated:
    quant_result: dict | None
```

### Pydantic v2 field_validator with Strict Mode

```python
# Source: docs.pydantic.dev/latest/concepts/strict_mode/
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, field_validator

class EVSignal(BaseModel):
    model_config = ConfigDict(strict=True)
    kelly_fraction: Decimal

    @field_validator("kelly_fraction")
    @classmethod
    def kelly_in_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") < v <= Decimal("0.25")):
            raise ValueError(f"kelly_fraction must be (0, 0.25], got {v}")
        return v

# Strict mode: must pass Decimal, not int or float
EVSignal(kelly_fraction=Decimal("0.05"))   # OK
EVSignal(kelly_fraction=0.05)              # ValidationError — int/float rejected
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `from langgraph.checkpoint.memory import MemorySaver` | `from langgraph.checkpoint.memory import InMemorySaver` | LangGraph 1.x | Old import name fails; use `InMemorySaver` |
| `langgraph` version 0.2.x / 0.3.x | `langgraph==1.1.0`, `langgraph-checkpoint==4.0.1` | 2025-2026 | Major version releases; separate `langgraph-checkpoint-sqlite` package required for SQLite |
| `SqliteSaver` for async graphs | `AsyncSqliteSaver` (from `langgraph.checkpoint.sqlite.aio`) | 0.2.x era | Sync checkpointer + async invocation hangs silently — critical breaking behavior |
| Separate `langgraph-checkpoint-sqlite` import | Same — still a separate install | Current | `pip install langgraph` alone does not include SQLite backend |
| `config_schema` on StateGraph | Deprecated — removal planned for v2.0.0 | LangGraph 0.6.0+ | Do not use `config_schema` parameter |

**Deprecated/outdated:**
- `MemorySaver`: Old class name — use `InMemorySaver`
- `SqliteSaver` for async invocations: Use `AsyncSqliteSaver` from `.sqlite.aio` submodule
- `config_schema` on StateGraph constructor: Deprecated since v0.6.0

---

## Open Questions

1. **AsyncSqliteSaver context manager lifespan in production**
   - What we know: `AsyncSqliteSaver.from_conn_string(path)` works as an async context manager per docs
   - What's unclear: Whether the connection should be opened once at app startup (singleton pattern) or per graph invocation (per-call context manager). The per-call pattern is safe but adds SQLite connection overhead per request.
   - Recommendation: For Phase 2 (testing infrastructure only), use per-call context manager. Phase 4 can revisit if connection overhead becomes measurable.

2. **GraphState initial population — who writes the game context fields**
   - What we know: `session_id`, `game_id`, `season`, etc. must be set before `ainvoke`; LangGraph treats the input dict as the initial state
   - What's unclear: Whether Phase 3 will pass game context via input state or via a dedicated "context loader" node before Master Router
   - Recommendation: Pass full initial state via `ainvoke(input_state, config)`. Do not add a context loader node in Phase 2. Phase 3 can add one if needed.

3. **`from __future__ import annotations` interaction with TypedDict**
   - What we know: Project convention requires `from __future__ import annotations` at top of all files; this enables string-based forward references
   - What's unclear: Whether `from __future__ import annotations` causes issues with LangGraph's runtime introspection of TypedDict fields
   - Recommendation: Keep `from __future__ import annotations` per project convention. If LangGraph introspection fails, add `from typing import get_type_hints` workaround. This is LOW confidence — verify in Wave 0 test.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ with pytest-asyncio 0.23+ |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — already configured with `asyncio_mode = "auto"` |
| Quick run command | `pytest tests/test_graph_state.py tests/test_pydantic_models.py -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-01 | `GraphState` TypedDict instantiates with all required fields | unit | `pytest tests/test_graph_state.py::test_graph_state_instantiation -x` | Wave 0 |
| INFRA-01 | `error` field reducer keeps first non-None error (concurrent write simulation) | unit | `pytest tests/test_graph_state.py::test_error_reducer_first_wins -x` | Wave 0 |
| INFRA-01 | Plain field (no reducer) last-write-wins behavior confirmed | unit | `pytest tests/test_graph_state.py::test_plain_field_last_write_wins -x` | Wave 0 |
| INFRA-02 | `route_request("quant_analysis")` returns `"quant_agent"` | unit | `pytest tests/test_graph_routing.py::test_route_quant_analysis -x` | Wave 0 |
| INFRA-02 | `route_request("odds_check")` returns `"arbitrage_agent"` | unit | `pytest tests/test_graph_routing.py::test_route_odds_check -x` | Wave 0 |
| INFRA-02 | `route_request("context_update")` returns `"context_agent"` | unit | `pytest tests/test_graph_routing.py::test_route_context_update -x` | Wave 0 |
| INFRA-02 | Graph with `request_type="quant_analysis"` invokes quant stub, not others | integration | `pytest tests/test_graph_routing.py::test_graph_dispatches_quant -x` | Wave 0 |
| INFRA-02 | State with `error` pre-set routes to END without touching any agent | integration | `pytest tests/test_graph_routing.py::test_error_short_circuits -x` | Wave 0 |
| INFRA-03 | `QuantParams` accepts valid input and rejects `season=1998` | unit | `pytest tests/test_pydantic_models.py::test_quant_params_season_range -x` | Wave 0 |
| INFRA-03 | `EVSignal` rejects `kelly_fraction=0.5` (>0.25) with `ValidationError` | unit | `pytest tests/test_pydantic_models.py::test_ev_signal_kelly_range -x` | Wave 0 |
| INFRA-03 | `EVSignal` rejects `trade_plan` with 4 items | unit | `pytest tests/test_pydantic_models.py::test_ev_signal_trade_plan_max3 -x` | Wave 0 |
| INFRA-03 | `EVSignal` rejects `kelly_fraction=0.05` (float) in strict mode | unit | `pytest tests/test_pydantic_models.py::test_strict_mode_rejects_float -x` | Wave 0 |
| INFRA-03 | `AgentOddsSnapshot.implied_probability` rejects values ≥ 1.0 | unit | `pytest tests/test_pydantic_models.py::test_odds_probability_range -x` | Wave 0 |
| INFRA-04 | Graph run with `InMemorySaver` + `thread_id` produces checkpoint retrievable via `aget_state` | integration | `pytest tests/test_checkpointing.py::test_checkpoint_persists_run -x` | Wave 0 |
| INFRA-04 | Same `thread_id` second invocation resumes from checkpoint (state is continuous) | integration | `pytest tests/test_checkpointing.py::test_checkpoint_replay -x` | Wave 0 |
| INFRA-04 | Different `thread_id` gets isolated state (no state bleed between threads) | integration | `pytest tests/test_checkpointing.py::test_thread_isolation -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_graph_state.py tests/test_pydantic_models.py tests/test_graph_routing.py -x -q --tb=short`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_graph_state.py` — covers INFRA-01: TypedDict instantiation, reducer behavior, concurrent-write simulation
- [ ] `tests/test_graph_routing.py` — covers INFRA-02: routing function unit tests + compiled graph dispatch integration tests
- [ ] `tests/test_pydantic_models.py` — covers INFRA-03: all 5 models, validation acceptance and rejection, strict mode behavior
- [ ] `tests/test_checkpointing.py` — covers INFRA-04: InMemorySaver persist/replay/isolation; AsyncSqliteSaver file-backed test
- [ ] `tests/conftest.py` — add `graph_checkpointer` fixture (InMemorySaver); add `built_graph` fixture (compiled StateGraph with InMemorySaver)
- [ ] `src/sportsbet/graph/__init__.py` — module init
- [ ] `src/sportsbet/graph/state.py` — GraphState TypedDict
- [ ] `src/sportsbet/graph/models.py` — all Pydantic I/O models
- [ ] `src/sportsbet/graph/router.py` — master_router node + route_request function
- [ ] `src/sportsbet/graph/nodes/` — stub node files
- [ ] `src/sportsbet/graph/builder.py` — StateGraph wiring
- [ ] Install: `uv add langgraph langgraph-checkpoint-sqlite`

---

## Sources

### Primary (HIGH confidence)

- LangGraph persistence docs (https://docs.langchain.com/oss/python/langgraph/persistence) — SqliteSaver/AsyncSqliteSaver setup, thread_id config, InMemorySaver, async/sync compatibility rules
- langgraph-checkpoint-sqlite PyPI (https://pypi.org/project/langgraph-checkpoint-sqlite/) — version 3.0.3, import paths: `from langgraph.checkpoint.sqlite import SqliteSaver`, `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver`
- langgraph PyPI (https://pypi.org/project/langgraph/) — version 1.1.0 released 2026-03-10, Python >=3.10
- langgraph-checkpoint PyPI (https://pypi.org/project/langgraph-checkpoint/) — version 4.0.1, `from langgraph.checkpoint.memory import InMemorySaver`
- LangGraph graph-api docs (https://docs.langchain.com/oss/python/langgraph/graph-api) — StateGraph builder pattern, add_node/add_edge/add_conditional_edges, START/END constants, Annotated reducer mechanism
- Pydantic strict mode docs (https://docs.pydantic.dev/latest/concepts/strict_mode/) — ConfigDict(strict=True) behavior, type coercion restrictions

### Secondary (MEDIUM confidence)

- LangGraph GitHub issue #1800 — sync checkpointer + async graph hangs silently (confirms Pitfall 1)
- LangGraph StateGraph reference (https://reference.langchain.com/python/langgraph/graph/state/StateGraph) — v0.6.0 docs; `config_schema` deprecation noted; compile() confirmed
- WebSearch: LangGraph routing pattern examples — conditional edges dict mapping pattern confirmed by multiple sources

### Tertiary (LOW confidence)

- `from __future__ import annotations` interaction with LangGraph TypedDict introspection — not verified against official docs; flag for Wave 0 validation
- AsyncSqliteSaver connection lifespan (singleton vs per-call) — official docs show per-call context manager pattern; singleton behavior unverified

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — LangGraph 1.1.0, checkpoint 4.0.1, checkpoint-sqlite 3.0.3 all verified via PyPI; import paths confirmed
- Architecture: HIGH — StateGraph builder pattern, Annotated reducers, conditional edges verified via official docs and reference
- Checkpointing: HIGH — AsyncSqliteSaver for async, InMemorySaver for tests, thread_id config all verified; sync/async hang behavior confirmed via GitHub issue
- Pydantic models: HIGH — v2 ConfigDict(strict=True), field_validator, Decimal behavior verified via official Pydantic docs; all match Phase 1 established patterns
- Pitfalls: HIGH — sync/async hang confirmed; reducer semantics verified; MemorySaver name change confirmed via PyPI

**Research date:** 2026-03-10
**Valid until:** 2026-06-10 (90 days — LangGraph is actively maintained but 1.x API is stabilizing)
