# Roadmap: Quant-Sports Agentic Analytics Platform

## Overview

Build a dependency-ordered NFL quant analytics backend: PostgreSQL data foundation first, then the LangGraph agent skeleton, then the Quant Engine probability core, then live context and odds ingestion, then the full arbitrage and risk output pipeline, and finally the Kinematic NGS alpha layer. Each phase gates the next — nothing upstream is written speculatively. The result is a fully functional, hallucination-proof +EV signal pipeline running locally on NFL data.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Data Foundation** - PostgreSQL schema, Alembic migrations, and memory-safe NFL data ingestion
- [ ] **Phase 2: Agent Infrastructure** - LangGraph graph skeleton, GraphState schema, and all Pydantic I/O models
- [ ] **Phase 3: Quant Engine** - Two-stage SQL validation gate, probability estimation, and backtesting module
- [ ] **Phase 4: Context and Odds Ingestion** - Live odds pipeline, staleness guards, and qualitative signal scraping
- [ ] **Phase 5: Arbitrage, Kelly, and Risk Controls** - EV calculation, fractional Kelly sizing, and correlation/drawdown gates
- [ ] **Phase 6: Kinematic Agent** - NGS tracking queries, geometric matchup signals, and season availability guards

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
**Plans**: TBD

### Phase 3: Quant Engine
**Goal**: The system can produce a statistically grounded true probability estimate from PostgreSQL data, validated through a two-stage SQL gate with no raw SQL ever leaving the LLM
**Depends on**: Phase 2
**Requirements**: QUANT-01, QUANT-02, QUANT-03, QUANT-04
**Success Criteria** (what must be TRUE):
  1. Feeding a malformed QuantParams payload (e.g., invalid season, injected SQL) raises ValidationError and never reaches the query builder
  2. A live Quant Agent call against Phase 1 data returns a QuantResult with true_probability, sample_size, confidence_interval, and data_source fields all populated from the database
  3. Raw sportsbook moneyline odds correctly convert to implied probabilities with vig removed (multiplicative and Pinnacle sharp methods both available)
  4. The backtesting module replays a set of historical QuantResult signals against known closing lines and outputs ROI and hit-rate metrics
**Plans**: TBD

### Phase 4: Context and Odds Ingestion
**Goal**: The system ingests live sportsbook odds and qualitative signals asynchronously, rejects stale data, and propagates structured context through GraphState
**Depends on**: Phase 2
**Requirements**: CTXT-01, CTXT-02, CTXT-03, CTXT-04
**Success Criteria** (what must be TRUE):
  1. A live Odds API call returns odds for an NFL game, writes a timestamped snapshot to PostgreSQL, and the budget manager correctly tracks the per-request spend against the configured daily cap
  2. An odds payload older than the configured staleness threshold (default: 5 minutes) is rejected before reaching the Arbitrage Agent — a test with a stale fixture confirms the rejection
  3. The injury/weather scraper runs against a target page and writes a structured binary state change (e.g., "Starting QB: Out") to the injury_reports table
  4. Context Agent updates GraphState with a ContextSignals object reflecting the current game state, and all downstream agents read from GraphState rather than re-fetching
**Plans**: TBD

### Phase 5: Arbitrage, Kelly, and Risk Controls
**Goal**: The full sequential pipeline (Context → Quant → Arbitrage → Aggregator) produces a +EV signal with fractional Kelly sizing, guarded by correlation stops and a daily drawdown gate
**Depends on**: Phase 3, Phase 4
**Requirements**: ARBT-01, ARBT-02, ARBT-03, ARBT-04
**Success Criteria** (what must be TRUE):
  1. An end-to-end pipeline run against a test game returns an ArbitrageSignal with raw EV percentage, a 3-bullet Trade Plan thesis, and a fractional Kelly fraction — never a flat bet size
  2. A CorrelationGuard test with two conflicting props (e.g., Over passing yards + Under total points) blocks both signals from reaching the output — the guard node runs before any recommendation is emitted
  3. After cumulative recommended exposure exceeds the configured daily drawdown limit, the Aggregator produces no further signals for the remainder of the simulated day
  4. An integration test running the full Context → Quant → Arbitrage → Aggregator chain passes end-to-end with real Phase 1 database data
**Plans**: TBD

### Phase 6: Kinematic Agent
**Goal**: The system queries NGS tracking data to produce geometric matchup exploit signals independent of box score history, with graceful handling of seasons with partial NGS coverage
**Depends on**: Phase 5
**Requirements**: KINE-01, KINE-02, KINE-03
**Success Criteria** (what must be TRUE):
  1. A Kinematic Agent query for a specific WR-CB matchup returns separation_at_catch, time_to_throw, and press_man_coverage_rate fields sourced from PostgreSQL NGS tables
  2. The agent produces a KinematicAnalysis object flagging a geometric mismatch (e.g., high-separation slot WR vs. high-press-rate CB) with a signal independent of the Quant Agent's box score probability
  3. Querying a season with partial NGS coverage returns None for unavailable fields instead of raising an exception or returning zero
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Foundation | 2/3 | In Progress|  |
| 2. Agent Infrastructure | 0/TBD | Not started | - |
| 3. Quant Engine | 0/TBD | Not started | - |
| 4. Context and Odds Ingestion | 0/TBD | Not started | - |
| 5. Arbitrage, Kelly, and Risk Controls | 0/TBD | Not started | - |
| 6. Kinematic Agent | 0/TBD | Not started | - |
