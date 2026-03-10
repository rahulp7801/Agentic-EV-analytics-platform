# Architecture Patterns

**Domain:** LangGraph multi-agent quant sports analytics
**Researched:** 2026-03-09
**Confidence note:** External tools (WebSearch, WebFetch, Context7) were unavailable during this research session. All findings are from training data (knowledge cutoff August 2025). LangGraph was at v0.2.x stable as of that cutoff. Treat all LangGraph API specifics as MEDIUM confidence — verify against official docs before implementing.

---

## Recommended Architecture

### High-Level Graph Topology

The system uses a **supervisor pattern** (also called the "master router" pattern in LangGraph). One central orchestrator node receives the initial request, routes to specialist sub-agents, aggregates their outputs into shared state, and produces the final structured output.

```
User Request
     |
     v
[Master Router Node]  <-- conditional edges based on request type
     |
     +---------> [Context Agent]     (qualitative signals)
     |                 |
     +---------> [Quant Agent]       (SQL execution)
     |                 |
     +---------> [Kinematic Agent]   (Next Gen Stats)
     |                 |
     +---------> [Arbitrage Agent]   (odds comparison)
     |                 |
     +---------> [Parlay Builder]    (correlated bets)
     |
     v
[Aggregator / Output Node]  <-- merges agent outputs
     |
     v
Structured Output (Pydantic model)
```

The Master Router does not run all agents for every query. It uses a conditional routing function that inspects the request type and activates only the necessary agents. This is the "selective activation" pattern and is critical for latency in a quant workflow.

### Execution Modes

Two execution modes apply to different query types:

**Sequential mode** — when agent B depends on agent A's output:
```
Context Agent --> Quant Agent --> Arbitrage Agent --> Output
```
The Arbitrage Agent needs the Quant Agent's true probability estimate before it can flag +EV discrepancies against live odds.

**Parallel mode** — when agents are independent for the same game context:
```
Context Agent --|
                |--> Aggregator --> Output
Kinematic Agent-|
```
Context signals and kinematic matchup data can be fetched simultaneously since neither depends on the other.

LangGraph supports both via `Send` (for fan-out to parallel branches) and standard sequential edges.

---

## Component Boundaries

| Component | Responsibility | Inputs | Outputs | Communicates With |
|-----------|---------------|--------|---------|-------------------|
| Master Router | Parse request, determine agent activation set, route via conditional edges | `UserRequest` state field | Updated `routing_plan` state field | All agents (outbound only) |
| Context Agent | Fetch and structure qualitative signals: injury reports, weather, public betting % | Game ID, team IDs | `ContextSignals` Pydantic model appended to state | Master Router (receives), Aggregator (sends) |
| Quant Agent | Build validated SQL queries, execute against PostgreSQL, compute true probability estimates | `QuantParams` (Pydantic-validated), game context from state | `QuantResult` with probability, sample size, confidence interval | Master Router (receives), Arbitrage Agent (sends) |
| Arbitrage Agent | Pull live odds from The Odds API, compare against `QuantResult.true_probability`, flag +EV bets, compute Kelly fraction | `QuantResult`, live odds | `ArbitrageSignal` list with Kelly sizing | Quant Agent (depends on), Aggregator (sends) |
| Kinematic Agent | Query Next Gen Stats tracking data (separation, time-to-throw, press coverage), identify geometric matchup exploits | Game ID, matchup parameters | `KinematicAnalysis` Pydantic model | Master Router (receives), Aggregator (sends) |
| Synthetic Parlay Builder | Identify correlated event pairs, apply correlation hard-stops, construct mathematically sound derivative bets | `ArbitrageSignal` list, correlation matrix | `ParlayBundle` with correlation-adjusted Kelly | Arbitrage Agent (depends on), Aggregator (sends) |
| Aggregator / Output Node | Merge all agent outputs, apply final risk checks (daily drawdown, correlation stops), produce terminal output | All agent outputs from state | Final `AnalysisReport` | All agents (receives) |
| PostgreSQL | Persistent store for historical NFL data, box scores, Next Gen Stats tracking | Writes from data pipeline | Query results to Quant Agent and Kinematic Agent | Quant Agent, Kinematic Agent (read); data ingestion pipeline (write) |

**Hard boundary rule:** No agent writes directly to another agent's state fields. All inter-agent communication goes through the shared `GraphState` TypedDict. This is the LangGraph contract.

---

## State Schema Design

This is the most architecturally critical decision in a LangGraph system. The state object is the single source of truth — every node reads from it and writes to it. Poorly designed state causes merge conflicts, lost data, and debugging nightmares.

### Recommended GraphState Structure

```python
from typing import TypedDict, Annotated, List, Optional
from operator import add
from pydantic import BaseModel

class GraphState(TypedDict):
    # --- Input ---
    request_type: str           # "game_analysis" | "arb_scan" | "parlay_build"
    game_id: str
    matchup: dict               # home_team, away_team, week, season

    # --- Routing ---
    routing_plan: List[str]     # which agents to activate, in order
    current_agent: str          # which agent is currently executing

    # --- Agent Outputs (append-only via reducers) ---
    context_signals: Optional[ContextSignals]      # written by Context Agent
    quant_result: Optional[QuantResult]            # written by Quant Agent
    kinematic_analysis: Optional[KinematicAnalysis]  # written by Kinematic Agent
    arbitrage_signals: Annotated[List[ArbitrageSignal], add]  # accumulates
    parlay_bundles: Annotated[List[ParlayBundle], add]        # accumulates

    # --- Risk Controls ---
    daily_drawdown_pct: float   # checked before any Kelly output
    correlation_flags: List[str]  # active correlation stops

    # --- Final Output ---
    analysis_report: Optional[AnalysisReport]
    errors: Annotated[List[str], add]  # accumulates errors from any agent
```

### Reducer Pattern

For list fields that multiple agents append to (arbitrage signals, errors), use `Annotated[List[T], add]` — this is LangGraph's built-in merge strategy that concatenates rather than overwrites. Without this, the last agent to write a list field wins and prior values are lost.

For single-value fields (quant_result, context_signals), no reducer is needed — they are written once by a single agent.

### Pydantic Models as State Values

Agent outputs should be Pydantic models, not raw dicts. This enforces the "LLM never guesses stats" contract at the type system level:

```python
class QuantResult(BaseModel):
    game_id: str
    true_probability: float          # model: 0.0-1.0
    implied_probability: float       # from market odds
    sample_size: int                 # rows in SQL result
    confidence_interval: tuple[float, float]
    sql_query_hash: str              # audit trail, not raw SQL
    data_source: str                 # "postgresql:nfl_historical"
    hallucination_guard: bool = True # always True if from DB

    class Config:
        # Reject extra fields — prevents LLM from injecting
        # fabricated fields into the model
        extra = "forbid"
```

---

## Data Flow

### Request Processing Flow

```
1. User sends request (game_id + analysis_type)
   |
2. Master Router parses request, builds routing_plan
   |
3. Conditional edge dispatches to first agent in plan
   |
4. Agent reads from GraphState, calls tool (DB query / API call)
   |
5. Agent writes Pydantic-validated output back to GraphState
   |
6. Conditional edge: more agents in plan? --> next agent
                     plan complete? ---------> Aggregator
   |
7. Aggregator applies risk checks, formats AnalysisReport
   |
8. Output delivered (CLI print / API response)
```

### Critical Data Flow Rule: SQL Path

The SQL execution path has a strict validation gate that must not be bypassed:

```
Quant Agent LLM generates query parameters (NOT raw SQL)
     |
     v
Pydantic validates QuantParams model (rejects invalid fields)
     |
     v
Query builder constructs parameterized SQL from validated params
     |
     v
psycopg2 / asyncpg executes with bound parameters (no string interpolation)
     |
     v
Results returned as typed dataframe
     |
     v
Pydantic validates QuantResult before writing to state
```

The LLM **never constructs raw SQL strings**. It populates a Pydantic model (`QuantParams`) and a separate query builder function constructs the actual SQL. This is the injection prevention + hallucination prevention boundary.

### Odds Arbitrage Flow

```
Quant Agent writes QuantResult to state (true_probability: 0.58)
     |
     v
Arbitrage Agent reads QuantResult from state
     |
     v
Arbitrage Agent calls The Odds API (external, real-time)
     |
     v
Market implied probability computed from best available odds
     |
     v
EV check: true_prob > implied_prob + edge_threshold?
     |
     YES: build ArbitrageSignal with Kelly fraction
     NO: drop signal
     |
     v
ArbitrageSignal appended to state (reducer merge)
```

---

## Patterns to Follow

### Pattern 1: Supervisor / Master Router

**What:** A single orchestrator node that routes to sub-agents via conditional edges. The router does not execute analysis — it only reads `request_type` and `routing_plan` and returns the next node name.

**When:** When different query types require different agent subsets (game analysis vs. arb scan vs. parlay construction).

**Implementation sketch:**
```python
def master_router(state: GraphState) -> str:
    """Returns next node name. No LLM call needed here."""
    plan = state["routing_plan"]
    if not plan:
        return "aggregator"
    return plan[0]  # pop handled by the agent itself

workflow = StateGraph(GraphState)
workflow.add_node("master_router", master_router)
workflow.add_conditional_edges(
    "master_router",
    master_router,
    {
        "context_agent": "context_agent",
        "quant_agent": "quant_agent",
        "kinematic_agent": "kinematic_agent",
        "aggregator": "aggregator",
    }
)
```

### Pattern 2: Tool-Calling Agents (not ReAct loops)

**What:** Each specialist agent is a single LangGraph node that calls one or two specific tools (DB query, API call). It is NOT a ReAct loop with unbounded tool calls.

**When:** Always — in a quant system, unbounded ReAct loops are unpredictable and dangerous. A Quant Agent that keeps retrying SQL queries until it likes the result is a liability.

**Why:** ReAct loops are appropriate for open-ended tasks (research, browsing). For a quant analytics system, each agent has a single, well-defined job. Bounding tool calls to 1-2 per agent invocation enforces predictability and makes the system auditable.

### Pattern 3: Checkpointing for Resumability

**What:** LangGraph's `MemorySaver` or PostgreSQL-backed `SqliteSaver`/`AsyncPostgresSaver` checkpointer serializes graph state after every node execution.

**When:** Enable from the start — retrofitting checkpointing is painful.

**Why:** If the Arbitrage Agent fails mid-run due to an API timeout, a checkpointer lets the graph resume from that node rather than re-running the entire pipeline (including the expensive SQL queries already completed).

```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("checkpoints.db")
app = workflow.compile(checkpointer=checkpointer)
```

### Pattern 4: Correlation Hard-Stops as Graph Guards

**What:** Before the Parlay Builder writes to state, a guard function checks `correlation_flags` in state and raises if conflicting exposures are detected.

**When:** Apply as a node condition, not inside the agent. Keep risk logic out of agent implementations.

```python
def correlation_guard(state: GraphState) -> str:
    """Runs before Parlay Builder. Returns skip or proceed."""
    if state.get("correlation_flags"):
        return "aggregator"  # skip parlay, go straight to output
    return "parlay_builder"
```

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: LLM as Data Source

**What:** Asking the LLM to recall statistics, injury histories, or historical odds within a prompt.

**Why bad:** LLMs hallucinate specific numbers with high confidence. One fabricated probability estimate corrupts the entire Kelly calculation downstream.

**Instead:** Every number in `QuantResult`, `KinematicAnalysis`, and `ArbitrageSignal` must have a `data_source` field referencing its PostgreSQL table or API response. Pydantic validates this field is present and non-empty.

### Anti-Pattern 2: Global Mutable State Outside GraphState

**What:** Using module-level Python variables or class attributes to share data between agents.

**Why bad:** Breaks LangGraph's deterministic replay (checkpointing re-executes nodes; if they read from external mutable state, replay produces different results).

**Instead:** All shared data lives in `GraphState`. Agent functions are pure: `state_in -> state_out`.

### Anti-Pattern 3: Raw SQL String Construction in LLM Output

**What:** Asking the LLM to write complete SQL queries that get executed directly.

**Why bad:** SQL injection risk, hallucinated column names, fabricated JOINs to tables that don't exist.

**Instead:** LLM populates a `QuantParams` Pydantic model. A deterministic query builder function converts validated params to parameterized SQL. The LLM never sees or produces raw SQL strings.

### Anti-Pattern 4: Fan-Out Without Result Merging Strategy

**What:** Running Context Agent and Kinematic Agent in parallel via `Send` but not defining how their outputs merge back into state.

**Why bad:** Without explicit reducers, parallel writes to the same state key cause a last-write-wins race condition.

**Instead:** Define reducers for all fields that can be written by parallel branches. Use `Annotated[T, reducer_fn]` on every shared list field.

### Anti-Pattern 5: Flat Kelly Sizing Without Drawdown Gate

**What:** Outputting Kelly fractions without checking current drawdown status first.

**Why bad:** Full Kelly on a losing streak accelerates ruin. This is the #1 quant trading mistake reproduced in sports betting contexts.

**Instead:** The Aggregator node checks `daily_drawdown_pct` before including any Kelly output in the final report. If drawdown exceeds threshold, output is flagged "NO BET TODAY — DRAWDOWN LIMIT" regardless of edge calculation.

---

## PostgreSQL Schema Design Considerations

### Core Tables

```sql
-- Game dimension table (one row per game)
CREATE TABLE games (
    game_id        VARCHAR(20) PRIMARY KEY,  -- e.g. "2024_01_KC_BAL"
    season         SMALLINT NOT NULL,
    week           SMALLINT NOT NULL,
    home_team      CHAR(3) NOT NULL,
    away_team      CHAR(3) NOT NULL,
    game_date      DATE NOT NULL,
    stadium        VARCHAR(100),
    weather_json   JSONB,                    -- temperature, wind, precip
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_games_season_week ON games(season, week);
CREATE INDEX idx_games_teams ON games(home_team, away_team);

-- Box scores (play aggregates per player per game)
CREATE TABLE player_game_stats (
    id             BIGSERIAL PRIMARY KEY,
    game_id        VARCHAR(20) REFERENCES games(game_id),
    player_id      VARCHAR(20) NOT NULL,
    team           CHAR(3) NOT NULL,
    position       VARCHAR(5),
    -- passing
    pass_attempts  SMALLINT,
    completions    SMALLINT,
    pass_yards     SMALLINT,
    pass_tds       SMALLINT,
    interceptions  SMALLINT,
    -- rushing
    carries        SMALLINT,
    rush_yards     SMALLINT,
    rush_tds       SMALLINT,
    -- receiving
    targets        SMALLINT,
    receptions     SMALLINT,
    rec_yards      SMALLINT,
    rec_tds        SMALLINT,
    -- fantasy
    fantasy_points NUMERIC(6,2)
);
CREATE INDEX idx_pgs_game_id ON player_game_stats(game_id);
CREATE INDEX idx_pgs_player_id ON player_game_stats(player_id);
CREATE INDEX idx_pgs_player_game ON player_game_stats(player_id, game_id);

-- Next Gen Stats (tracking, per-play aggregated per player per game)
CREATE TABLE ngs_stats (
    id                     BIGSERIAL PRIMARY KEY,
    game_id                VARCHAR(20) REFERENCES games(game_id),
    player_id              VARCHAR(20) NOT NULL,
    season                 SMALLINT NOT NULL,
    week                   SMALLINT NOT NULL,
    -- passing NGS
    avg_time_to_throw      NUMERIC(5,2),
    avg_air_yards          NUMERIC(6,2),
    aggressiveness         NUMERIC(5,2),   -- % of passes into tight windows
    -- receiving NGS
    avg_separation         NUMERIC(5,2),   -- yards of separation at catch point
    avg_intended_air_yards NUMERIC(6,2),
    catch_pct              NUMERIC(5,2),
    -- rushing NGS
    efficiency             NUMERIC(5,2),
    percent_attempts_gte_8_defenders NUMERIC(5,2)
);
CREATE INDEX idx_ngs_player_season ON ngs_stats(player_id, season);
CREATE INDEX idx_ngs_game_id ON ngs_stats(game_id);

-- Live odds snapshots (time-series, append-only)
CREATE TABLE odds_snapshots (
    id             BIGSERIAL PRIMARY KEY,
    game_id        VARCHAR(20) REFERENCES games(game_id),
    sportsbook     VARCHAR(50) NOT NULL,
    market_type    VARCHAR(30) NOT NULL,  -- "spread" | "moneyline" | "total" | "player_prop"
    line           NUMERIC(6,2),
    price          SMALLINT,             -- American odds, e.g. -110
    snapped_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_odds_game_market ON odds_snapshots(game_id, market_type);
CREATE INDEX idx_odds_snapped_at ON odds_snapshots(snapped_at DESC);

-- Injury reports
CREATE TABLE injury_reports (
    id             BIGSERIAL PRIMARY KEY,
    player_id      VARCHAR(20) NOT NULL,
    team           CHAR(3) NOT NULL,
    week           SMALLINT NOT NULL,
    season         SMALLINT NOT NULL,
    report_date    DATE NOT NULL,
    status         VARCHAR(20),          -- "Out" | "Doubtful" | "Questionable" | "Full"
    practice_status VARCHAR(30),
    injury_type    VARCHAR(100)
);
CREATE INDEX idx_injury_player_week ON injury_reports(player_id, season, week);
```

### Indexing Strategy

**Rule:** Every foreign key column needs an index. Every column used in WHERE clauses needs an index. Multi-year datasets with improper indexing cause full table scans that will make the Quant Agent unusably slow.

- Composite index on `(player_id, game_id)` — the most common Quant Agent join pattern
- Composite index on `(season, week)` on games — common filter pattern
- Descending index on `odds_snapshots.snapped_at` — always querying most recent snapshot

**Partitioning consideration:** If loading 5+ years of NFL data (~17 weeks x 16 games x ~50 players = ~13,000 rows/season in `player_game_stats`), partitioning by season on `player_game_stats` and `ngs_stats` is optional but provides clean data management and faster season-specific queries.

---

## Suggested Build Order

The build order follows the dependency graph: components that others depend on must be built first.

### Phase 1: Data Foundation
**Build first.** Nothing else works without data in the database.

1. PostgreSQL schema creation (migrations via Alembic)
2. `nfl_data_py` ingestion script — bulk load historical seasons into `player_game_stats` and `games`
3. NGS data ingestion into `ngs_stats`
4. Basic index validation (EXPLAIN ANALYZE on representative queries)

**Why first:** The Quant Agent and Kinematic Agent are only testable against real data. Mocking the DB produces false confidence in the pipeline.

### Phase 2: Core Agent Infrastructure
**Build second.** Establishes the graph skeleton before adding agents.

1. `GraphState` TypedDict definition
2. All Pydantic models for agent I/O (`QuantParams`, `QuantResult`, `ContextSignals`, etc.)
3. `StateGraph` scaffold with Master Router and all node stubs (nodes that return empty state updates)
4. Checkpointer setup

**Why second:** Defining the state contract before writing agent logic prevents the most common LangGraph mistake: agents that write incompatible fields to shared state.

### Phase 3: Quant Agent + SQL Layer
**Build third.** The revenue-generating core of the system.

1. Query builder — converts `QuantParams` to parameterized SQL
2. Pydantic validation on `QuantParams` (reject before any DB call)
3. Database connection pool (asyncpg or psycopg2)
4. `QuantResult` construction with probability estimation
5. Unit tests: validate that no raw SQL string is ever produced from LLM output

**Why third:** Arbitrage Agent, Parlay Builder, and the final Kelly output all depend on `QuantResult`. Validate this layer thoroughly before building anything that depends on it.

### Phase 4: Context Agent + Odds Ingestion
**Build fourth.** Parallel to Quant Agent in execution but lower risk (no SQL involved).

1. The Odds API client with rate limiting and retry logic
2. Odds snapshot writer to `odds_snapshots` table
3. Context Agent: injury report scraper (nfl.com or Pro Football Reference)
4. `ContextSignals` Pydantic model and state write
5. Integration test: verify Context Agent output matches expected schema

### Phase 5: Arbitrage Agent + Kelly
**Build fifth.** Depends on Phase 3 (QuantResult) and Phase 4 (live odds).

1. EV calculation: `ev = true_prob * win_payout - (1 - true_prob) * stake`
2. Kelly formula: `f* = (bp - q) / b` where b = decimal odds - 1, p = true_prob, q = 1 - true_prob
3. Fractional Kelly (apply 0.25x or 0.5x multiplier — never full Kelly)
4. Drawdown gate: daily_drawdown_pct check before outputting any Kelly fraction
5. `ArbitrageSignal` Pydantic model validation

### Phase 6: Kinematic Agent
**Build sixth.** Independent of Arbitrage Agent; depends only on NGS data (Phase 1) and state schema (Phase 2).

1. NGS query patterns: separation leaders, time-to-throw against pressure, press coverage success rates
2. Matchup matrix: WR separation vs. CB press rate — the "geometric exploit" signal
3. `KinematicAnalysis` Pydantic model

### Phase 7: Synthetic Parlay Builder
**Build last.** Depends on ArbitrageSignals from Phase 5.

1. Correlation matrix computation (correlated events: same game rushing + team total over)
2. Hard-stop rules: block anti-correlated parlays (QB passing yards over + team rushing TD over on same team)
3. `ParlayBundle` construction with correlation-adjusted Kelly sizing
4. Correlation guard node in graph

### Phase 8: Integration and Terminal Output
**Build last.** Wire everything together.

1. Master Router routing logic (conditional edges for all request types)
2. Aggregator node (merges all agent outputs, final risk checks)
3. `AnalysisReport` final output model
4. CLI interface for local testing

---

## Scalability Considerations

| Concern | At 100 queries/day | At 10K queries/day | At 1M queries/day |
|---------|-------------------|--------------------|-------------------|
| DB reads | Single connection, synchronous fine | Connection pool (asyncpg, 10-20 connections) | Read replicas, query result cache |
| Odds API | Rate limit headroom fine | Cache snapshots every 5 min, don't hit API per query | Dedicated odds feed subscription |
| Agent concurrency | Single-threaded fine | AsyncIO LangGraph execution | Distributed agents (Celery or Ray) |
| Checkpointing | SQLite fine | PostgreSQL checkpointer | Dedicated checkpoint store |
| Memory | Full dataframe loads fine | Column pruning, generators for aggregations | Partitioned queries, streaming |

For v1 (local dev, NFL only), the "At 100 queries/day" column applies. Do not over-engineer for scale that doesn't exist yet. The architectural decisions that matter for v1 are correctness (Pydantic validation, no SQL hallucination) and data integrity (proper indexing, audit trails).

---

## Sources

**Confidence assessment:**
All findings are from training knowledge (cutoff August 2025). External research tools were unavailable during this session.

| Claim | Confidence | Basis |
|-------|------------|-------|
| LangGraph supervisor pattern | HIGH | Core LangGraph design pattern, well-documented in training data through v0.2 |
| `TypedDict` + `Annotated` reducer pattern | HIGH | Fundamental LangGraph state management, stable API |
| `SqliteSaver` / checkpoint API | MEDIUM | API was stable but check current LangGraph docs for `AsyncPostgresSaver` availability |
| `Send` for parallel fan-out | MEDIUM | Verify current API — was `Send` in v0.2, may have evolved |
| Pydantic `extra = "forbid"` pattern | HIGH | Standard Pydantic v2 behavior, stable |
| PostgreSQL schema design | HIGH | Standard relational design, no LangGraph-specific concerns |
| Kelly Criterion formula | HIGH | Mathematical fact, not framework-dependent |

**Verify before implementing:**
- Current LangGraph version (may be v0.3+ by implementation time)
- `AsyncPostgresSaver` availability and import path
- `Send` API for parallel branches (import path and usage may have changed)
- `MemorySaver` vs `SqliteSaver` vs `AsyncPostgresSaver` checkpointer choice

Official LangGraph docs: https://langchain-ai.github.io/langgraph/
LangGraph multi-agent concepts: https://langchain-ai.github.io/langgraph/concepts/multi_agent/
