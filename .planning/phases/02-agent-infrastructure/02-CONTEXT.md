# Phase 2: Agent Infrastructure - Context

**Gathered:** 2026-03-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the LangGraph graph skeleton: GraphState TypedDict with Annotated reducers, Master Router with conditional edges routing to 3 specialist stub agents, all Pydantic I/O contracts defined, and SqliteSaver checkpointing active. No agent logic written — only the wiring and contracts that every downstream phase will depend on.

</domain>

<decisions>
## Implementation Decisions

### Request Types & Routing
- 3 request types in v1: `quant_analysis` → Quant Agent, `odds_check` → Arbitrage Agent, `context_update` → Context Agent
- Master Router always routes to exactly one agent per request — no fan-out parallelism in Phase 2
- Graph is invoked via `await graph.ainvoke(...)` — async Python function, not CLI
- Stub agents return hardcoded fixture state (static QuantResult/EVSignal instance) so Phase 3 can develop against a real interface contract immediately

### GraphState Shape
- `session_id: str` (UUID), `request_type: str`, `created_at: datetime` — for checkpointing replay and log correlation
- `game_id: str`, `season: int`, `week: int`, `home_team: str`, `away_team: str`, `injury_flags: dict[str, str]`, `weather_json: dict | None` — game context fields
- `error: str | None` — agents set this to signal failure; Master Router routes to END if set
- Bankroll params (`bankroll_usd`, `max_kelly_fraction`) live in `Settings` (config.py), NOT in GraphState — prevents mutation mid-graph
- All fields written by multiple agents use `Annotated` reducers (INFRA-01 requirement)

### Pydantic I/O Models
- **QuantParams**: `game_id: str`, `season: int`, `week: int`, `posteam: str`, `stat_type: Literal['passing', 'rushing', 'receiving']`, `filters: dict[str, Any]`
- **QuantResult**: output of Quant Agent — historical win rates and query results (fields defined by Phase 3, stub returns fixture)
- **EVSignal**: `ev_percentage: Decimal`, `true_probability: Decimal`, `implied_probability: Decimal`, `kelly_fraction: Decimal`, `trade_plan: list[str]` (max 3 items), `market_type: str`
- **AgentOddsSnapshot** (separate from ingestion model): `game_id: str`, `sportsbook: str`, `market_type: str`, `implied_probability: Decimal` (already converted from American odds), `snapped_at: datetime` — agent layer never sees raw American odds
- **GameState**: matches GraphState game context fields — `game_id`, `season`, `week`, `home_team`, `away_team`, `injury_flags`, `weather_json`
- **Validation rules**: range guards only — `kelly_fraction: 0 < x ≤ 0.25`, `ev_percentage: x > 0`, `season: 1999–2030`
- All models: Pydantic v2 with `ConfigDict(strict=True)` — no v1 patterns

### Checkpointing
- **Backend**: SqliteSaver for runtime, MemorySaver for tests — avoid AsyncPostgresSaver until LangGraph 0.3.x import path is verified
- **Scope**: checkpoint after every node (LangGraph default behavior — no extra code)
- **Replay**: caller passes `thread_id` to `ainvoke(config={'configurable': {'thread_id': '...'}})` — explicit, no magic
- **Test isolation**: tests inject MemorySaver with a fresh UUID `thread_id` per test — no disk I/O, no cleanup needed

### Claude's Discretion
- QuantResult field shape (Phase 3 will define what queries return)
- Exact Annotated reducer implementations (standard `operator.add` or custom merge)
- SqliteSaver file path convention (e.g., `.checkpoints/sportsbet.sqlite`)
- Graph compilation and StateGraph builder pattern

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `sportsbet.config.Settings`: Pydantic v2 BaseSettings — bankroll params should be added here, not to GraphState
- `sportsbet.db.connection.create_async_pool()`: asyncpg pool for hot-path agent queries — agents will use this for DB access
- `sportsbet.db.connection.get_sync_engine()`: psycopg engine — available for any sync operations
- `sportsbet.db.models.Base` + 5 ORM models: integration points for agents querying game/player/odds data

### Established Patterns
- Pydantic v2 with `ConfigDict` — `model_config = ConfigDict(strict=True)` on all agent I/O models (matches Phase 1 pattern)
- `from __future__ import annotations` at top of all Python files
- `Optional[X]` used for nullable fields (Phase 1 pattern)
- `Decimal` (not `float`) for all monetary/probability values — from db/models.py pattern

### Integration Points
- `sportsbet.config.settings` → add `bankroll_usd: float = 10000.0` and `max_kelly_fraction: float = 0.25` fields
- `sportsbet.db.connection` → agents import `create_async_pool` for runtime queries
- New module: `src/sportsbet/graph/` — StateGraph, GraphState, router, stub nodes, Pydantic models

</code_context>

<specifics>
## Specific Ideas

- Stub agents return static fixture instances of their output model — gives Phase 3 a real contract to code against immediately
- `error: str | None` on GraphState is the single error propagation mechanism — no exceptions crossing node boundaries
- The `AgentOddsSnapshot` separation from `OddsSnapshotCreate` (ingestion model) keeps the agent layer clean — agents work with probabilities, not American odds integers

</specifics>

<deferred>
## Deferred Ideas

- AsyncPostgresSaver — revisit once LangGraph 0.3.x API is confirmed stable (Phase 4 or later)
- Fan-out parallelism via Send API — deferred to Phase 5 when Arbitrage Agent needs to run concurrently with Quant Agent
- CLI invocation wrapper — deferred to post-v1 ops tooling
- `confidence_score` on EVSignal — deferred to Phase 5 when scoring logic is defined

</deferred>

---

*Phase: 02-agent-infrastructure*
*Context gathered: 2026-03-10*
