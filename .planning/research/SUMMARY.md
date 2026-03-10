# Project Research Summary

**Project:** Quant Sports Agentic Analytics Platform
**Domain:** Multi-agent quantitative +EV sports betting analytics (NFL-first)
**Researched:** 2026-03-09
**Confidence:** MEDIUM (all external web/API tools were blocked during research; findings from training data through August 2025)

## Executive Summary

This is a quantitative sports analytics backend built on a LangGraph multi-agent directed graph. The architecture follows the supervisor pattern: a Master Router node dispatches work to specialist sub-agents (Context, Quant, Arbitrage, Kinematic, Parlay Builder), each of which writes typed Pydantic outputs to a shared `GraphState` TypedDict. The core value proposition is a hallucination-proof pipeline where the LLM orchestrates logic but never supplies statistics — every number in the system must be traceable to a PostgreSQL query result or verified API response. The stack consensus is strong: Python 3.12, LangGraph 0.2.x, Pydantic v2 strict mode, asyncpg for hot-path database access, httpx/tenacity for The Odds API, and uv for dependency management.

The recommended build approach is strictly dependency-ordered. The data foundation (PostgreSQL schema + nfl_data_py ingestion + composite indexes) must exist before any agent can be meaningfully tested. The graph state schema and all Pydantic I/O models must be defined before any agent node is written — retrofitting reducers and output contracts after agents are coded is the single most common LangGraph mistake. The quant core (probability estimation + EV + Kelly sizing) must be validated before the arbitrage and parlay layers are added. Kinematic (NGS tracking) and the synthetic parlay builder are high-alpha but deferred to after the core pipeline is proven.

The three non-negotiable risks are: (1) LLM hallucination reaching quantitative fields — prevented by `data_source` annotations and strict write-scope enforcement per agent; (2) Kelly over-sizing on correlated positions — prevented by a `CorrelationGuard` graph node that runs before any bet recommendation is emitted; and (3) LangGraph shared state reducer conflicts causing silent data loss — prevented by defining `Annotated[T, reducer_fn]` for every shared list field before writing any agent. Ignore any one of these three and the platform will produce confident-looking output from corrupt data.

---

## Key Findings

### Recommended Stack

The stack is mature and well-integrated. LangGraph (0.2.x, verify for 0.3.x at implementation time) provides the directed state graph with native checkpointing — use `SqliteSaver` for local dev, `AsyncPostgresSaver` for production. Pydantic v2 (strictly native v2 decorators, `ConfigDict(strict=True)`, never the v1 compatibility shim) is the validation backbone for all LLM outputs. asyncpg is the only acceptable driver for hot-path database reads; SQLAlchemy 2.0 is restricted to migrations and schema management. nfl_data_py is the canonical NFL data source but requires disciplined usage (year-by-year loads, immediate column pruning). The entire dependency graph is managed with uv.

**Core technologies:**
- `langgraph 0.2.x`: Directed agent graph with supervisor pattern and checkpointing — maps directly to Master Router + specialist sub-agent topology
- `pydantic v2 (strict)`: Runtime validation of all LLM outputs before any DB write or EV calculation — the hallucination firewall
- `asyncpg 0.29+`: Fastest async PostgreSQL driver for hot-path quant queries (3x faster than psycopg2 async)
- `nfl_data_py 0.3+`: Historical NFL box scores, play-by-play, and Next Gen Stats (partial) — free, covers 1999 onward
- `httpx 0.27+ / tenacity 8.3+`: Async Odds API client with exponential backoff and quota management
- `alembic 1.13+`: Schema migrations — required for multi-year NFL schema evolution
- `structlog 24.1+`: Structured JSON logging with agent run IDs — mandatory for audit trail
- `uv 0.4+`: Package manager replacing pip/poetry — 10-100x faster, lockfile-based

**What must not be used:** full `langchain` package (use `langchain-core` only), `psycopg2` (sync, maintenance mode), `requests` in async code, raw SQL strings from LLM output, flat bet sizing, `pandas` without immediate column pruning on multi-year loads, `pickle` for agent state.

See `.planning/research/STACK.md` for full version table and rejected alternatives.

### Expected Features

The feature set is divided by hard dependency: data foundation gates everything; probability model gates EV; EV gates Kelly; Kelly gates bet recommendations; correlation analysis gates the parlay builder.

**Must have (table stakes):**
- Live odds ingestion from multiple books (The Odds API, 40+ sportsbooks) — without real-time lines EV math is stale
- Implied probability calculation with vig removal (Pinnacle sharp method) — raw odds are meaningless for EV
- +EV flag with edge percentage — the core actionable signal
- Fractional Kelly bet sizing (0.25x standard, 0.5x cap) — flat bets are quant malpractice
- Historical NFL box score data via nfl_data_py (5+ seasons minimum)
- Injury/availability signal integration — the #1 external variable for NFL lines
- Pydantic validation layer blocking LLM hallucination before any DB write
- Win/loss tracking with ROI reporting

**Should have (differentiators):**
- Multi-agent LangGraph routing with selective agent activation — most tools are monolithic pipelines
- Kinematic Agent using NGS tracking data (separation, time-to-throw, press coverage) — underused alpha layer
- Context Agent bundling weather/surface/travel/divisional signals into structured game-state JSON
- Correlation hard-stops preventing conflicting exposure within a single slate
- Game-state JSON as shared agent memory — single source of truth updated by Context Agent, read by all others
- Dynamic SQL query generation via Pydantic-validated LLM params (not raw SQL)

**Defer (v2+):**
- Synthetic Parlay Builder with correlation analysis (requires covariance infrastructure to be stable first)
- Backtesting framework (critical for trust, but validates the pipeline retrospectively)
- Frontend terminal (backend-first; high-density quant UI deferred until math is validated)
- CLV (closing line value) tracking analysis UI (start logging line snapshots from day one; analysis deferred)
- NBA pipeline (NFL-only until pipeline is proven)
- OAuth / multi-user auth

See `.planning/research/FEATURES.md` for full dependency chain diagram and MVP rationale.

### Architecture Approach

The system uses LangGraph's supervisor pattern: a static compiled `StateGraph` with a Master Router node that dispatches via conditional edges to specialist agents, then an Aggregator node that merges outputs, applies final risk checks (drawdown gate, correlation stops), and emits a typed `AnalysisReport`. Agents run sequentially when there is a dependency chain (Context → Quant → Arbitrage) and in parallel via `Send` fan-out when independent (Context and Kinematic can run simultaneously). All inter-agent communication is through `GraphState` — no agent writes to another agent's namespace directly. The SQL path has a mandatory two-stage validation gate: LLM populates a `QuantParams` Pydantic model, a deterministic query builder constructs parameterized SQL, and asyncpg executes with bound parameters. The LLM never produces raw SQL strings.

**Major components:**
1. **Master Router** — parses `request_type`, builds `routing_plan`, dispatches via conditional edges; no LLM call in the router itself
2. **Context Agent** — fetches injury reports, weather, surface, public betting %; writes `ContextSignals` to state; runs first in every graph execution
3. **Quant Agent** — LLM populates `QuantParams` → deterministic query builder → asyncpg → `QuantResult` with `true_probability`, sample size, confidence interval, and `data_source` field
4. **Arbitrage Agent** — reads `QuantResult`, fetches live odds from The Odds API, computes EV, emits `ArbitrageSignal` list with fractional Kelly fractions; depends on Quant Agent output
5. **Kinematic Agent** — queries NGS tracking data (separation, time-to-throw, press man rates); writes `KinematicAnalysis`; independent of Arbitrage Agent
6. **Correlation Guard** — graph node (not inside Parlay Builder) that checks `correlation_flags` before any parlay recommendation is allowed through
7. **Synthetic Parlay Builder** — constructs correlation-adjusted multi-leg bets from `ArbitrageSignal` list; deferred to post-core
8. **Aggregator** — merges all agent outputs, applies drawdown gate, emits final `AnalysisReport`
9. **PostgreSQL** — append-only `odds_snapshots` table, `player_game_stats`, `ngs_stats`, `injury_reports`, `games`; composite indexes on all common query patterns

See `.planning/research/ARCHITECTURE.md` for full state schema, SQL path diagram, and PostgreSQL DDL.

### Critical Pitfalls

1. **LLM hallucination reaching quantitative fields** — add `data_source: Literal["db", "dataframe", "api"]` annotation to every Pydantic model carrying stats; enforce at the graph level that LLM nodes have write access only to qualitative fields; any numeric stat field without a traceable source must raise `ValidationError` before state update. Address before writing any agent node.

2. **Kelly over-sizing on correlated positions** — implement `CorrelationGuard` as a graph node (not inside the Arbitrage Agent), running a correlation matrix check against all currently open positions before any bet recommendation is emitted; treat same-game multi-props as a single Kelly bundle. Address before any live odds integration.

3. **LangGraph reducer conflicts causing silent lost writes** — define `Annotated[T, reducer_fn]` for every `GraphState` field that more than one agent can write; separate agent-owned namespaces (`context_agent_state`, `quant_agent_state`) within global state; write a concurrent-run state schema test before any parallel agent execution. Address in the state schema definition step, before writing any agent.

4. **nfl_data_py OOM on multi-year loads** — never load more than one season at a time; define a column whitelist per data type and drop all other columns immediately after `import_pbp_data` returns; call `del df; gc.collect()` between seasons; use chunked PostgreSQL writes (`chunksize=1000`). Address in ingestion script design, before first data load.

5. **Pydantic v2 validator bypass via v1 compatibility shim** — pin `pydantic>=2.0,<3.0` from day one; never use `@validator` or `@root_validator`; use only `@field_validator(mode='before'|'after')` and `@model_validator`; set `ConfigDict(strict=True)` on all LLM output models; write a malformed-input test fixture. Address before any Pydantic model is written.

6. **Odds API rate limit exhaustion and stale odds windows** — implement a request budget manager (warn at 70%, hard-stop at 90% of monthly quota); cache odds snapshots with TTL in PostgreSQL or Redis; assert `odds_age_seconds < MAX_STALE_THRESHOLD` before any EV calculation. Address before the live polling loop runs against the real API.

7. **Missing composite indexes causing full table scans on multi-year queries** — define all indexes in Alembic migration scripts before loading any data; required: `(season, week)`, `(posteam, season)`, `(play_type, season, week)`, `(passer_player_id, season)`, `(player_id, game_id)`; add `EXPLAIN ANALYZE` CI assertions that no hot query uses `Seq Scan`. Address in schema DDL, before first data load.

---

## Implications for Roadmap

All four research files agree on the same dependency-ordered phase structure. The architecture's build order, the features' dependency chain, and the pitfalls' phase warnings all point to the same sequence.

### Phase 1: Data Foundation

**Rationale:** Every other component depends on data existing in PostgreSQL. No agent can be meaningfully tested without it. The pitfalls that must be avoided here (OOM ingestion, missing indexes, `to_sql` replace bug, Pydantic v1 shim, column-pruning discipline) are all setup-time decisions that are expensive to retrofit.

**Delivers:** PostgreSQL schema with Alembic migrations; nfl_data_py ingestion pipeline (year-by-year, column-whitelisted, gc-managed); NGS data load; injury report table; all composite indexes; `current_nfl_season()` utility; Pydantic v2 baseline configuration; structured logging setup with structlog.

**Addresses (from FEATURES.md):** Historical NFL box score data (5+ seasons), injury/availability signal storage, data integrity / no-hallucination foundation.

**Avoids (from PITFALLS.md):** nfl_data_py OOM (Pitfall 4), missing composite indexes (Pitfall 7), `to_sql` replace-vs-append bug (Pitfall 12), Pydantic v2 validator bypass (Pitfall 5), hardcoded season/week constants (Pitfall 14).

**Research flag:** Standard patterns — PostgreSQL schema design and nfl_data_py usage are well-documented. No deeper research needed before implementation.

---

### Phase 2: Core Agent Infrastructure (Graph Skeleton)

**Rationale:** The `GraphState` TypedDict and all Pydantic I/O models must be defined before any agent node is written. This is the LangGraph contract: state schema first, agent logic second. Retrofitting reducers or output model contracts after agents are coded causes the most common class of LangGraph bugs (reducer conflicts, lost writes).

**Delivers:** `GraphState` TypedDict with all reducers defined; all agent I/O Pydantic models (`QuantParams`, `QuantResult`, `ContextSignals`, `KinematicAnalysis`, `ArbitrageSignal`, `ParlayBundle`, `AnalysisReport`); `StateGraph` scaffold with Master Router and node stubs; checkpointer setup (SqliteSaver for local dev); graph-level pre-commit hook asserting no numeric stat fields are written by LLM nodes.

**Addresses (from FEATURES.md):** Modular agent graph (agents replaceable without pipeline rewrite); game-state JSON as shared agent memory.

**Avoids (from PITFALLS.md):** LangGraph reducer conflicts (Pitfall 3), graph definition vs. runtime state confusion (Pitfall 9), LLM context window stuffing with raw DataFrames (Pitfall 13).

**Research flag:** LangGraph state management patterns are well-documented but API details (especially `Send` for parallel fan-out, `AsyncPostgresSaver` import path) must be verified against current docs at implementation time. Recommend a brief verification step before coding graph infrastructure.

---

### Phase 3: Quant Agent and SQL Validation Layer

**Rationale:** The Quant Agent is the revenue-generating core. Every downstream component (Arbitrage Agent, Kelly sizing, Parlay Builder) depends on `QuantResult.true_probability`. This layer must be validated thoroughly before anything builds on top of it. The two-stage SQL validation gate (LLM → QuantParams → deterministic query builder → parameterized SQL) is the single most important correctness boundary in the system.

**Delivers:** `QuantParams` Pydantic model with `ConfigDict(strict=True)`; deterministic query builder (no raw SQL from LLM); asyncpg connection pool; probability estimation from DB query results; `QuantResult` with `data_source` annotation and `sql_query_hash`; unit tests asserting zero raw SQL strings emerge from LLM output; sample size gate (N >= 50 before Kelly fraction is emitted).

**Addresses (from FEATURES.md):** Probability model, +EV calculation foundation, data integrity / no-LLM-hallucination guardrails.

**Avoids (from PITFALLS.md):** LLM hallucination reaching quantitative fields (Pitfall 1), raw SQL string construction (Anti-Pattern 3 from ARCHITECTURE.md), Kelly over-sizing on small sample win rates (Pitfall 10).

**Research flag:** Standard patterns. Pydantic v2 and asyncpg are HIGH confidence. The query builder pattern is well-understood.

---

### Phase 4: Context Agent and Odds Ingestion

**Rationale:** The Context Agent must run first in every graph execution cycle, and the Arbitrage Agent depends on both `QuantResult` (Phase 3) and live odds. Building odds ingestion in parallel with the Quant Agent implementation is efficient — neither depends on the other during build time. The request budget manager and odds cache must be in place before the polling loop runs against the real API.

**Delivers:** The Odds API async client (httpx + tenacity) with request budget manager and odds-age assertion; `odds_snapshots` table writer; Context Agent with injury report scraper (Playwright + BeautifulSoup); weather/surface/travel signals; `ContextSignals` Pydantic model and state write; scraper response shape validation (silent block detection).

**Addresses (from FEATURES.md):** Live odds ingestion from multiple books, implied probability with vig removal, injury/availability signal integration, structured game-state JSON.

**Avoids (from PITFALLS.md):** Odds API rate limit exhaustion (Pitfall 6), sport key naming changes (Pitfall 15), silent scraper block detection (Pitfall 11).

**Research flag:** The Odds API sport key naming and current rate limit tiers should be verified against live API documentation at implementation time. Playwright anti-bot mitigation patterns are moderately documented but may need testing against specific target pages.

---

### Phase 5: Arbitrage Agent, Kelly Sizing, and Correlation Guards

**Rationale:** This phase assembles the core output pipeline: EV calculation, fractional Kelly sizing, and the risk controls that must gate all bet recommendations. The `CorrelationGuard` node must be a graph-level node (not inside the Arbitrage Agent) to keep risk logic orthogonal to agent logic. The drawdown gate in the Aggregator must be in place before any Kelly fraction appears in output.

**Delivers:** EV formula (`ev = true_prob * payout - (1 - true_prob) * stake`); fractional Kelly (0.25x standard, 0.5x cap); `CorrelationGuard` graph node with configurable `r > 0.4` threshold; daily drawdown gate in Aggregator; `ArbitrageSignal` Pydantic model; full sequential agent chain (Context → Quant → Arbitrage → Aggregator) with integration tests end-to-end.

**Addresses (from FEATURES.md):** +EV flag with edge percentage, Kelly Criterion bet sizing, correlation hard-stops, win/loss tracking with ROI foundation.

**Avoids (from PITFALLS.md):** Kelly over-sizing on correlated positions (Pitfall 2), flat Kelly without drawdown gate (Anti-Pattern 5 from ARCHITECTURE.md), fractional Kelly on small samples (Pitfall 10).

**Research flag:** Standard patterns. Kelly Criterion math is HIGH confidence. Correlation matrix computation is standard. No deeper research needed.

---

### Phase 6: Kinematic Agent (NGS Alpha Layer)

**Rationale:** Independent of the Arbitrage Agent; depends only on NGS data (loaded in Phase 1) and the state schema (defined in Phase 2). Deferred until the core pipeline is validated because the base probability model should be stable before an enhancement layer is added. This is the primary competitive differentiation — no mainstream +EV tool uses NGS separation, time-to-throw, or press-man coverage rates as geometric matchup signals.

**Delivers:** NGS query patterns (separation leaders, time-to-throw vs. pressure, press coverage success rates); matchup matrix (WR separation vs. CB press rate); `KinematicAnalysis` Pydantic model; integration into Aggregator's final probability enhancement.

**Addresses (from FEATURES.md):** Kinematic Agent with NGS tracking data — the primary alpha differentiator.

**Avoids (from PITFALLS.md):** LLM hallucination (data_source enforcement from Phase 2 applies here too); nfl_data_py NGS partial coverage gaps must be handled gracefully (treat missing NGS fields as `None`, not zero).

**Research flag:** Needs verification. nfl_data_py's NGS field availability for current and recent seasons should be confirmed before planning this phase in detail — the research notes NGS coverage is partial. Recommend a brief `/gsd:research-phase` to verify available NGS fields and any API changes.

---

### Phase 7: Synthetic Parlay Builder

**Rationale:** Requires the full `ArbitrageSignal` list from Phase 5 and empirically computed correlation coefficients from historical data. Must not be built until both the single-bet pipeline is stable and the correlation measurement infrastructure exists. The correlation sign error (Pitfall 8) is the most dangerous mistake in this phase — intuition about which events are positively correlated is often wrong.

**Delivers:** Historical correlation coefficient computation from PostgreSQL (minimum N=200 per prop pair); hard-stop rules for anti-correlated legs; `ParlayBundle` with correlation-adjusted Kelly; `CorrelationGuard` extension for multi-leg validation; documented list of empirically positively correlated prop pairs in NFL data.

**Addresses (from FEATURES.md):** Synthetic parlay builder with correlation analysis — rare and valuable among consumer tools.

**Avoids (from PITFALLS.md):** Correlation sign error in parlay construction (Pitfall 8), naive independent-probability multiplication (Anti-Feature from FEATURES.md).

**Research flag:** Empirical NFL prop correlation data may need research. The specific prop pairs that are demonstrably positively correlated (e.g., QB passing yards + WR1 receiving yards) should be validated against historical data before the builder's recommendation logic is coded.

---

### Phase Ordering Rationale

- **Dependency chain is non-negotiable:** PostgreSQL schema before agents; state schema before agent nodes; `QuantResult` before `ArbitrageSignal`; single-bet pipeline before parlay builder. Violating any link forces a rewrite of downstream components.
- **Risk front-loading:** The three critical pitfalls (hallucination guard, reducer contracts, correlation guard) are addressed in the first three phases, before any live data or real money math is introduced.
- **Validation before enhancement:** Phase 5 produces a working, testable single-bet pipeline before Phase 6 adds the NGS alpha layer. This means the base model can be validated in backtesting independently of the kinematic enhancement.
- **Deferral is deliberate:** Frontend, backtesting, CLV analysis UI, and multi-sport pipelines are explicitly out of scope for v1 — not because they are unimportant, but because premature investment in those areas before the math is validated is a classic failure mode.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 2 (Graph Infrastructure):** Verify current LangGraph version (may be 0.3.x by implementation), confirm `AsyncPostgresSaver` import path, confirm `Send` API for parallel fan-out — these are MEDIUM confidence API surface details.
- **Phase 4 (Odds Ingestion):** Verify current Odds API sport key naming, rate limits, and `bookmakers` filter syntax against live API documentation.
- **Phase 6 (Kinematic Agent):** Verify nfl_data_py NGS field availability for current seasons — partial coverage noted in research, specifics unclear.

**Phases with standard patterns (skip research-phase):**
- **Phase 1 (Data Foundation):** PostgreSQL schema design, Alembic migrations, pandas memory management — all well-documented, HIGH confidence.
- **Phase 3 (Quant Agent):** Pydantic v2 strict validation, asyncpg query patterns, parameterized SQL — all HIGH confidence.
- **Phase 5 (Kelly + Arbitrage):** Kelly Criterion math, EV formula, fractional Kelly implementation — mathematical facts, HIGH confidence.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Core choices (Pydantic v2, asyncpg, httpx, uv, pytest) are HIGH confidence. LangGraph version (0.2 vs 0.3+), APScheduler 4.0 stable release, and psycopg3 3.2.x are MEDIUM — verify with `pip index versions` at project init |
| Features | MEDIUM | Feature set derived from training knowledge of OddsJam, SharpSide, Action Network Pro. No live competitor research was possible. Core +EV / Kelly / correlation features are well-established quant betting conventions (HIGH); specific competitor feature gaps are MEDIUM |
| Architecture | MEDIUM-HIGH | LangGraph supervisor pattern, TypedDict + Annotated reducer, Pydantic `extra="forbid"`, PostgreSQL schema design — all HIGH confidence. `AsyncPostgresSaver` availability and `Send` API details are MEDIUM — verify against current LangGraph docs |
| Pitfalls | HIGH | Mathematical pitfalls (Kelly correlation blindness, small-sample over-sizing) are HIGH confidence. LangGraph-specific pitfalls (reducer conflicts, graph vs. runtime state confusion) are MEDIUM-HIGH — well-documented pattern from training data. API-specific pitfalls (Odds API rate limits, sport key naming) are MEDIUM |

**Overall confidence:** MEDIUM-HIGH

The architecture, stack rationale, and mathematical foundations are solid. The primary uncertainty is specific API surface details in LangGraph (version evolution), The Odds API (current rate limits and key naming), and nfl_data_py NGS field coverage. These are implementation-time verification items, not design blockers.

### Gaps to Address

- **LangGraph version:** All LangGraph research assumes v0.2.x (August 2025 training cutoff). By implementation, v0.3+ may be current with changed APIs. Run `pip index versions langgraph` and check official docs for `AsyncPostgresSaver`, `Send`, and checkpointer changes before Phase 2 begins.
- **The Odds API current state:** Sport key naming (`americanfootball_nfl`), rate limits per tier, and `bookmakers` filter syntax should be verified against the live `/sports` endpoint before Phase 4 begins. Do not hardcode sport keys.
- **nfl_data_py NGS coverage:** Research notes Next Gen Stats coverage via nfl_data_py is "partial." Before Phase 6 design, verify which NGS fields (separation, time-to-throw, press coverage, rush efficiency) are available for which seasons and at what granularity (per-play vs. per-game aggregates).
- **APScheduler 4.0 stable release:** Marked as "RC as of Aug 2025." Confirm stable release status before including in production dependencies. If not yet stable, pin to 3.x or use `asyncio` task scheduling directly.
- **Correlation coefficient data for parlay builder:** The specific NFL prop pairs with empirically positive correlation need to be validated against historical data before Phase 7 is designed. Do not rely on intuition.

---

## Sources

### Primary (HIGH confidence)
- Pydantic v2 official docs — validation patterns, `ConfigDict(strict=True)`, `@field_validator`, `extra="forbid"`; https://docs.pydantic.dev/latest/
- asyncpg official docs — async PostgreSQL driver, connection pooling, COPY API; https://magicstack.github.io/asyncpg/
- SQLAlchemy 2.0 docs — async session, ORM patterns, Alembic integration
- uv package manager — reproducible builds, lockfile management; https://docs.astral.sh/uv/
- Kelly Criterion — mathematical foundations (training knowledge, HIGH confidence as mathematical fact)
- PostgreSQL indexing — B-tree composite indexes, BRIN for time-series (standard relational design)

### Secondary (MEDIUM confidence)
- LangGraph documentation (training data, August 2025 cutoff) — supervisor pattern, TypedDict state, Annotated reducers, checkpointing; https://langchain-ai.github.io/langgraph/
- nfl_data_py GitHub — `import_pbp_data`, `import_ngs_data` API, dataset characteristics; https://github.com/nflverse/nfl_data_py
- psycopg3 docs — async driver, COPY operations; https://www.psycopg.org/psycopg3/docs/
- The Odds API v4 — sport keys, rate limits, bookmakers filter (training knowledge; verify live)
- Professional betting platforms (OddsJam, SharpSide, Action Network Pro, Pikkit, Bet Labs) — feature set benchmarking from training knowledge

### Tertiary (MEDIUM-LOW confidence)
- APScheduler 4.0 — async-native scheduling; RC status as of August 2025, verify stable release
- Competitor feature sets (OddsJam, SharpSide current state) — training knowledge only; validate with live research when web access is available

---
*Research completed: 2026-03-09*
*Ready for roadmap: yes*
