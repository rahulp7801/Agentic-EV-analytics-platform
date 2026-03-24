# Roadmap: Quant-Sports Agentic Analytics Platform

## Overview

Build a dependency-ordered NFL quant analytics backend: PostgreSQL data foundation first, then the LangGraph agent skeleton, then the Quant Engine probability core, then live context and odds ingestion, then the full arbitrage and risk output pipeline, and finally the Kinematic NGS alpha layer. Each phase gates the next — nothing upstream is written speculatively. The result is a fully functional, hallucination-proof +EV signal pipeline running locally on NFL data.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Data Foundation** - PostgreSQL schema, Alembic migrations, and memory-safe NFL data ingestion (completed 2026-03-10)
- [ ] **Phase 2: Agent Infrastructure** - LangGraph graph skeleton, GraphState schema, and all Pydantic I/O models
- [x] **Phase 3: Quant Engine** - Two-stage SQL validation gate, probability estimation, and backtesting module (completed 2026-03-13)
- [x] **Phase 4: Context and Odds Ingestion** - Live odds pipeline, staleness guards, and qualitative signal scraping (completed 2026-03-15)
- [x] **Phase 5: Arbitrage, Kelly, and Risk Controls** - EV calculation, fractional Kelly sizing, and correlation/drawdown gates (completed 2026-03-15)
- [x] **Phase 6: Kinematic Agent** - NGS tracking queries, geometric matchup signals, and season availability guards (completed 2026-03-21)
- [x] **Phase 7: Production Runtime Wiring** - Wire all Phase 5/6 nodes into create_graph_with_sqlite(), fix GraphState schema, and connect vig removal to EV pipeline (completed 2026-03-22)
- [x] **Phase 8: Data Pipeline and Backtest Completion** - Persist live odds for CLV tracking, fix avg_time_to_throw query gap, and add BacktestEngine CLI entry point (completed 2026-03-22)
- [x] **Phase 9: Critical Pipeline Gap Closure** - Fix air_yards column error, wire staleness gate, and fix CLV price field (completed 2026-03-22)
- [x] **Phase 10: Player Prop and NBA Data Layer** - PlayerPropSnapshot ORM, PropParams/PropResult models, and NBA player stats ingestion (completed 2026-03-23)
- [x] **Phase 11: NFL Player Prop Quant Engine** - PropQueryBuilder, NFL prop probability from historical distributions, kinematic integration (completed 2026-03-23)
- [x] **Phase 12: NBA Player Prop Quant Engine** - NBAQueryBuilder, NormalDist CDF probability, pace/rest/defensive rating adjustments (completed 2026-03-23)
- [x] **Phase 13: Player Prop Arbitrage and Pipeline Wiring** - PropArbitrageAgent, extended CorrelationGuard, full LangGraph prop pipeline wiring (completed 2026-03-23)
- [x] **Phase 14: Prop Integration Gap Closure** - Wire live prop odds persistence, fix NBA prop arbitrage sport key mismatch in production factory, declare prop_filters in GraphState (completed 2026-03-23)
- [x] **Phase 15: Context and Vig Completion** - Add NBA game-level odds ingestion to OddsAPIPoller and context agent; wire Pinnacle sharp devig as selectable config option (completed 2026-03-24)

## Phase Details

### Phase 1: Data Foundation
**Goal**: The database exists, NFL data is loaded, and every downstream agent has trustworthy structured data to query
**Depends on**: Nothing (first phase)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04
**Success Criteria** (what must be TRUE):
  1. Running `SELECT COUNT(*) FROM play_by_play WHERE season = 2023` returns a non-zero row count with sub-second response
  2. Alembic migration `upgrade head` runs cleanly on a fresh PostgreSQL instance and creates all tables with composite indexes
  3. The ingestion script loads 5+ seasons of NFL PBP data without OOM crash, with gc.collect() called between each season
  4. Odds snapshot rows can be written to and queried from `odds_snapshots` with a timestamped CLV-ready schema
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Project scaffold, settings, utils, and test infrastructure stubs (Wave 0)
- [x] 01-02-PLAN.md — SQLAlchemy ORM models, Alembic migration with all composite indexes, migration tests green
- [ ] 01-03-PLAN.md — nflreadpy PBP/NGS/player-stats ingestion, odds snapshot writer, CLI entry point

### Phase 2: Agent Infrastructure
**Goal**: The LangGraph graph skeleton compiles and routes, all agent I/O contracts are defined, and checkpointing is active before any agent logic is written
**Depends on**: Phase 1
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04
**Success Criteria** (what must be TRUE):
  1. The compiled StateGraph can be invoked with a test request_type and the Master Router correctly dispatches to the matching stub node via conditional edges
  2. All Pydantic I/O models (QuantParams, QuantResult, OddsSnapshot, EVSignal, GameState) instantiate, validate, and reject malformed inputs with ValidationError
  3. GraphState fields written by multiple agents use Annotated reducers — a concurrent-write test confirms no silent data loss
  4. SqliteSaver checkpointing persists a graph run to disk and the run can be replayed from the saved checkpoint
**Plans**: 3 plans

Plans:
- [ ] 02-01-PLAN.md — Pydantic v2 I/O models: QuantParams, QuantResult, EVSignal, AgentOddsSnapshot, GameState with validation (Wave 1, TDD)
- [ ] 02-02-PLAN.md — GraphState TypedDict, Master Router, 3 stub agents, compiled StateGraph (Wave 2)
- [ ] 02-03-PLAN.md — SqliteSaver checkpointing integration, bankroll config fields, MemorySaver test fixtures (Wave 3)

### Phase 3: Quant Engine
**Goal**: The system can produce a statistically grounded true probability estimate from PostgreSQL data, validated through a two-stage SQL gate with no raw SQL ever leaving the LLM
**Depends on**: Phase 2
**Requirements**: QUANT-01, QUANT-02, QUANT-03, QUANT-04
**Success Criteria** (what must be TRUE):
  1. Feeding a malformed QuantParams payload (e.g., invalid season, injected SQL) raises ValidationError and never reaches the query builder
  2. A live Quant Agent call against Phase 1 data returns a QuantResult with true_probability, sample_size, confidence_interval, and data_source fields all populated from the database
  3. Raw sportsbook moneyline odds correctly convert to implied probabilities with vig removed (multiplicative and Pinnacle sharp methods both available)
  4. The backtesting module replays a set of historical QuantResult signals against known closing lines and outputs ROI and hit-rate metrics
**Plans**: 3 plans

Plans:
- [ ] 03-01-PLAN.md — quant subpackage scaffold, QueryBuilder two-stage gate, asyncpg executor, real quant_agent closure (Wave 1, TDD)
- [ ] 03-02-PLAN.md — vig removal module: american_to_raw_prob, multiplicative devig, power devig (Wave 1, TDD, parallel with 03-01)
- [ ] 03-03-PLAN.md — backtesting module: BacktestSignal, BacktestReport, BacktestEngine with CLV replay (Wave 2, TDD)

### Phase 4: Context and Odds Ingestion
**Goal**: The system ingests live sportsbook odds and qualitative signals asynchronously, rejects stale data, and propagates structured context through GraphState
**Depends on**: Phase 2
**Requirements**: CTXT-01, CTXT-02, CTXT-03, CTXT-04
**Success Criteria** (what must be TRUE):
  1. A live Odds API call returns odds for an NFL game, writes a timestamped snapshot to PostgreSQL, and the budget manager correctly tracks the per-request spend against the configured daily cap
  2. An odds payload older than the configured staleness threshold (default: 5 minutes) is rejected before reaching the Arbitrage Agent — a test with a stale fixture confirms the rejection
  3. The injury/weather scraper runs against a target page and writes a structured binary state change (e.g., "Starting QB: Out") to the injury_reports table
  4. Context Agent updates GraphState with a ContextSignals object reflecting the current game state, and all downstream agents read from GraphState rather than re-fetching
**Plans**: 4 plans

Plans:
- [ ] 04-01-PLAN.md — Wave 0 foundation: InjuryReport ORM model, Alembic migration 0002, ContextSignals model, GraphState extension, 8 test stubs, dep installs (Wave 0)
- [ ] 04-02-PLAN.md — OddsAPIPoller with budget manager and is_stale() staleness guard (Wave 1, TDD, parallel with 04-03)
- [ ] 04-03-PLAN.md — InjuryWeatherScraper via ESPN Core API, write_injury_reports DB writer (Wave 1, TDD, parallel with 04-02)
- [ ] 04-04-PLAN.md — make_context_agent closure factory, graph.py context_node wiring, all 8 tests green (Wave 2)

### Phase 5: Arbitrage, Kelly, and Risk Controls
**Goal**: The full sequential pipeline (Context → Quant → Arbitrage → Aggregator) produces a +EV signal with fractional Kelly sizing, guarded by correlation stops and a daily drawdown gate
**Depends on**: Phase 3, Phase 4
**Requirements**: ARBT-01, ARBT-02, ARBT-03, ARBT-04
**Success Criteria** (what must be TRUE):
  1. An end-to-end pipeline run against a test game returns an ArbitrageSignal with raw EV percentage, a 3-bullet Trade Plan thesis, and a fractional Kelly fraction — never a flat bet size
  2. A CorrelationGuard test with two conflicting props (e.g., Over passing yards + Under total points) blocks both signals from reaching the output — the guard node runs before any recommendation is emitted
  3. After cumulative recommended exposure exceeds the configured daily drawdown limit, the Aggregator produces no further signals for the remainder of the simulated day
  4. An integration test running the full Context → Quant → Arbitrage → Aggregator chain passes end-to-end with real Phase 1 database data
**Plans**: 3 plans

Plans:
- [ ] 05-01-PLAN.md — arbitrage subpackage (kelly.py, ev.py), make_arbitrage_agent closure, Wave 0 test stubs + TDD (Wave 1)
- [ ] 05-02-PLAN.md — CorrelationGuard conflict detection and Aggregator drawdown gate modules, TDD (Wave 2)
- [ ] 05-03-PLAN.md — graph.py wiring (arbitrage_node, correlation_guard, aggregator), route_from_master extension, end-to-end integration test (Wave 3)

### Phase 6: Kinematic Agent
**Goal**: The system queries NGS tracking data to produce geometric matchup exploit signals independent of box score history, with graceful handling of seasons with partial NGS coverage
**Depends on**: Phase 5
**Requirements**: KINE-01, KINE-02, KINE-03
**Success Criteria** (what must be TRUE):
  1. A Kinematic Agent query for a specific WR-CB matchup returns separation_at_catch, time_to_throw, and press_man_coverage_rate fields sourced from PostgreSQL NGS tables
  2. The agent produces a KinematicAnalysis object flagging a geometric mismatch (e.g., high-separation slot WR vs. high-press-rate CB) with a signal independent of the Quant Agent's box score probability
  3. Querying a season with partial NGS coverage returns None for unavailable fields instead of raising an exception or returning zero
**Plans**: 2 plans

Plans:
- [ ] 06-01-PLAN.md — kinematic subpackage (models, availability guard, matchup executor) with TDD (Wave 1)
- [ ] 06-02-PLAN.md — make_kinematic_agent closure, GraphState extension, graph wiring, end-to-end integration test (Wave 2)

### Phase 7: Production Runtime Wiring
**Goal:** Wire all Phase 5/6 nodes into the production runtime factory, fix the GraphState schema gaps, and connect vig removal to the EV pipeline so every production invocation uses real risk controls and mathematically correct EV math
**Depends on:** Phase 6
**Requirements:** QUANT-02, ARBT-01, ARBT-03, ARBT-04, KINE-01, KINE-02
**Gap Closure:** Closes gaps INT-01, INT-02, INT-04 from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. `create_graph_with_sqlite()` accepts and wires `arbitrage_node`, `correlation_guard_node`, `aggregator_node`, and `kinematic_node` — a smoke test confirms all four nodes are reachable via conditional routing
  2. `GraphState` TypedDict declares `receiver_gsis_id: str` — a kinematic agent invocation with a real GSIS ID produces a non-empty NGS query result instead of silently querying for `""`
  3. `_extract_odds_snapshot()` calls `american_to_raw_prob` + a devig function before constructing `AgentOddsSnapshot.implied_probability` — a test confirms devigged probability differs from raw division result

Plans:
- [ ] 07-01-PLAN.md — Extend create_graph_with_sqlite() with Phase 5/6 nodes, add receiver_gsis_id to GraphState, wire vig removal in odds pipeline

### Phase 8: Data Pipeline and Backtest Completion
**Goal:** Persist live odds to the database for CLV tracking, fix the avg_time_to_throw SELECT gap in the kinematic query, and expose BacktestEngine via a CLI entry point so all v1 modules have a production caller
**Depends on:** Phase 7
**Requirements:** QUANT-04, DATA-03, KINE-01
**Gap Closure:** Closes gaps INT-03, INT-05, and QUANT-04 partial from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. `make_context_agent` calls `write_odds_snapshot()` after fetching and validating live odds — a test confirms at least one row appears in `odds_snapshots` after a context agent run
  2. `_SEPARATION_QUERY` SELECT list includes `AVG(ngs_stats.avg_time_to_throw)` with the correct QB JOIN — a kinematic query for a QB with NGS data returns a non-None `avg_time_to_throw` field in `KinematicAnalysis`
  3. A CLI entry point (e.g., `python -m sportsbet.quant.backtest`) runs `BacktestEngine` against a fixture dataset and prints ROI and hit-rate metrics without manual import

Plans:
- [ ] 08-01-PLAN.md — Call write_odds_snapshot() from context agent, add avg_time_to_throw to _SEPARATION_QUERY, add BacktestEngine CLI entry point

### Phase 9: Critical Pipeline Gap Closure
**Goal:** Fix the three production-blocking gaps found by the v1.0 milestone audit — missing play_by_play columns that break all quant queries, unwired staleness gate that passes stale odds unconditionally, and null price written to odds snapshots that voids CLV tracking
**Depends on:** Phase 8
**Requirements:** QUANT-03, QUANT-01, CTXT-02, DATA-03, ARBT-01
**Gap Closure:** Closes gaps GAP-1, GAP-2, GAP-3 from v1.0 audit

**Success Criteria** (what must be TRUE):
  1. A live `run_quant_query` call against PostgreSQL returns a `QuantResult` with a non-None `true_probability` — no `column "air_yards" does not exist` error
  2. An odds payload with `snapped_at` older than 5 minutes is rejected by `make_context_agent` — `ContextSignals.odds_snapshot` is set to None for stale inputs
  3. `write_odds_snapshot()` writes a row with a non-null `price` field — CLV comparison has a usable numeric reference

Plans:
- [x] 09-01-PLAN.md — Add air_yards/two_point_attempt/complete_pass to ORM + migration + PBP_COLUMNS; wire is_stale() in make_context_agent; fix write_odds_snapshot price

### Phase 10: Player Prop and NBA Data Layer
**Goal:** Extend the odds pipeline to ingest NFL and NBA player prop lines, add NBA player box score ingestion via nba_api, and define all Pydantic models and ORM tables needed for the prop quant engine
**Depends on:** Phase 9
**Requirements:** PROP-01, PROP-02, NBA-01

**Success Criteria** (what must be TRUE):
  1. `OddsAPIPoller` fetches player prop markets (passing/rushing/receiving for NFL; points/rebounds/assists/3PM for NBA) and writes `PlayerPropSnapshot` rows to PostgreSQL with non-null implied probability
  2. `PropParams` and `PropResult` Pydantic models validate a full prop query request and reject malformed inputs with `ValidationError`
  3. `nba_api` ingestion loads at least 2 seasons of NBA player box scores (points, rebounds, assists, 3PM, steals, blocks, minutes) into a PostgreSQL `nba_player_stats` table with season/game/player composite index

Plans:
- [ ] 10-01-PLAN.md — PlayerPropSnapshot ORM + Alembic migration; extend OddsAPIPoller with NFL + NBA prop endpoints; PropParams/PropResult Pydantic models
- [ ] 10-02-PLAN.md — nba_api ingestion: NBAPlayerStats ORM + migration, year-by-year loader with gc.collect(), CLI entry point

### Phase 11: NFL Player Prop Quant Engine
**Goal:** Produce statistically grounded true probability estimates for NFL player props using historical distributions from PostgreSQL data, with kinematic signal integration for receiving props
**Depends on:** Phase 10
**Requirements:** PROP-03, PROP-04

**Success Criteria** (what must be TRUE):
  1. A `PropQuantAgent` query for a passing yards prop returns a `PropResult` with `true_probability`, `sample_size`, and `confidence_interval` sourced entirely from PostgreSQL — no LLM-hallucinated stats
  2. The two-stage Pydantic gate (`PropParams` → `PropQueryBuilder` → parameterized SQL) rejects malformed prop queries before any SQL executes
  3. A receiving yards prop query for a WR with NGS data incorporates the kinematic agent's `separation_at_catch` and `press_man_coverage_rate` signals into the probability estimate

Plans:
- [ ] 11-01-PLAN.md — NFL prop distribution calculator: passing/rushing/receiving historical distributions, PropQueryBuilder two-stage gate, PropQuantAgent closure (TDD)
- [ ] 11-02-PLAN.md — Kinematic signal integration for receiving props: read KinematicAnalysis from GraphState and adjust PropResult probability

### Phase 12: NBA Player Prop Quant Engine
**Goal:** Produce probability estimates for NBA player props using pace-adjusted historical distributions, factoring in opponent defensive rating, rest days, and home/away context
**Depends on:** Phase 10
**Requirements:** PROP-05, NBA-02

**Success Criteria** (what must be TRUE):
  1. An `NBAQuantAgent` query for a points O/U prop returns a `PropResult` with `true_probability` sourced from PostgreSQL NBA stats — pace-adjusted and opponent-defensive-rating-weighted
  2. A back-to-back rest penalty is applied to player distributions — a query with `rest_days=0` returns a meaningfully different `true_probability` than the same query with `rest_days=2`
  3. Double-double and PRA combo props are supported — `PropParams` accepts `prop_type` values of `double_double` and `pra` and returns statistically valid probability estimates

Plans:
- [ ] 12-01-PLAN.md — NBA prop distribution calculator: points/rebounds/assists/3PM/PRA/double-double, pace adjustment, rest penalty, defensive rating factor (TDD)
- [ ] 12-02-PLAN.md — NBAQuantAgent closure, GraphState extension for NBA context (pace, rest, home_away), NBAContextSignals Pydantic model

### Phase 13: Player Prop Arbitrage and Full Pipeline Wiring
**Goal:** Wire NFL and NBA prop quant signals into a PropArbitrageAgent that produces EV% and 3-bullet Trade Plans with fractional Kelly sizing, extended CorrelationGuard for correlated props, and full LangGraph integration
**Depends on:** Phase 11, Phase 12
**Requirements:** PROP-06, PROP-07

**Success Criteria** (what must be TRUE):
  1. A `PropArbitrageAgent` call for a mispriced passing yards prop returns an `ArbitrageSignal` with raw EV percentage, a 3-bullet Trade Plan thesis, and a fractional Kelly fraction — never a flat bet size
  2. `CorrelationGuard` blocks simultaneous Over passing yards + Under receiving yards signals on the same game — extended conflict matrix covers prop-to-prop and prop-to-game-total correlations
  3. An end-to-end pipeline run (Context → PropQuant → PropArbitrage → Aggregator) for an NFL prop and an NBA prop both complete with non-None EV signals against real database data

Plans:
- [x] 13-01-PLAN.md — PropArbitrageAgent: EV% calculation, 3-bullet Trade Plan, fractional Kelly sizing for props; extended CorrelationGuard prop conflict matrix
- [x] 13-02-PLAN.md — LangGraph wiring: prop_quant_node, nba_quant_node, prop_arbitrage_node added to create_graph_with_sqlite(); route_from_master extended; end-to-end integration test

### Phase 14: Prop Integration Gap Closure
**Goal:** Close the three integration gaps identified by the v1.0 milestone audit — wire live prop odds persistence so player_prop_snapshots is populated, fix the NBA prop arbitrage sport key mismatch that silently returns ev_signal=None for all NBA prop requests, and declare prop_filters in GraphState TypedDict to restore contract integrity
**Depends on:** Phase 13
**Requirements:** PROP-01, PROP-06, NBA-02
**Gap Closure:** Closes PROP-01 (prop persistence unwired), PROP-06 (NBA sport key mismatch), NBA-02 (downstream EVSignal failure), INFRA-01 (prop_filters TypedDict gap)

**Success Criteria** (what must be TRUE):
  1. After a context agent run, the `player_prop_snapshots` table contains at least one row with a non-null `implied_probability` — `fetch_player_props()` result is persisted via `write_player_prop_snapshot()`
  2. An NBA prop pipeline invocation (`nba_quant_agent → prop_arbitrage_agent`) returns a non-None `EVSignal` — the sport mismatch in `create_graph_with_sqlite()` is resolved so `nba_prop_result` is read correctly
  3. `GraphState` TypedDict declares `prop_filters: dict[str, object]` — `state.get("prop_filters", {})` in `prop/agents.py` and `nba_agents.py` is backed by an explicit TypedDict field

Plans:
- [ ] 14-01-PLAN.md — Wire fetch_player_props → write_player_prop_snapshot; fix NBA prop_arbitrage sport mismatch; add prop_filters to GraphState

### Phase 15: Context and Vig Completion
**Goal:** Complete the two deferred v1 capabilities — add NBA game-level odds ingestion to OddsAPIPoller and context agent so NBA market context flows through GraphState, and wire the Pinnacle sharp devig method as a config-selectable alternative to multiplicative devig so QUANT-02 is fully satisfied
**Depends on:** Phase 14
**Requirements:** QUANT-02, CTXT-01, CTXT-04
**Gap Closure:** Closes QUANT-02 partial (Pinnacle method orphaned), CTXT-04 partial (NFL-only context agent), Flow 2 (NBA game context broken)

**Success Criteria** (what must be TRUE):
  1. `OddsAPIPoller` exposes a `fetch_nba_odds()` method and `make_context_agent` routes NBA sport requests to it — an NBA context agent run produces a `ContextSignals` object with a non-None `odds_snapshot`
  2. A config flag (`vig_method: "multiplicative" | "pinnacle"`) controls which devig function `_extract_odds_snapshot` calls — setting `vig_method="pinnacle"` causes `remove_vig_power` to be used instead of `remove_vig_multiplicative`, with a test confirming the outputs differ
  3. All existing NFL context agent tests continue to pass — the NBA routing addition is additive and does not break the NFL flow

Plans:
- [ ] 15-01-PLAN.md — Add fetch_nba_odds() to OddsAPIPoller; update make_context_agent for sport routing; wire remove_vig_power via config flag

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Foundation | 3/3 | Complete   | 2026-03-10 |
| 2. Agent Infrastructure | 2/3 | In Progress|  |
| 3. Quant Engine | 3/3 | Complete   | 2026-03-13 |
| 4. Context and Odds Ingestion | 4/4 | Complete   | 2026-03-15 |
| 5. Arbitrage, Kelly, and Risk Controls | 3/3 | Complete   | 2026-03-15 |
| 6. Kinematic Agent | 2/2 | Complete   | 2026-03-21 |
| 7. Production Runtime Wiring | 1/1 | Complete   | 2026-03-22 |
| 8. Data Pipeline and Backtest Completion | 1/1 | Complete   | 2026-03-22 |
| 9. Critical Pipeline Gap Closure | 1/1 | Complete   | 2026-03-22 |
| 10. Player Prop and NBA Data Layer | 2/2 | Complete    | 2026-03-23 |
| 11. NFL Player Prop Quant Engine | 2/2 | Complete    | 2026-03-23 |
| 12. NBA Player Prop Quant Engine | 2/2 | Complete    | 2026-03-23 |
| 13. Player Prop Arbitrage and Pipeline Wiring | 2/2 | Complete    | 2026-03-23 |
| 14. Prop Integration Gap Closure | 1/1 | Complete    | 2026-03-23 |
| 15. Context and Vig Completion | 1/1 | Complete   | 2026-03-24 |
