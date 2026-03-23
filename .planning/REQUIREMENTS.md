# Requirements: Quant-Sports Agentic Analytics Platform

**Defined:** 2026-03-10
**Core Value:** The Quant Agent must produce statistically grounded +EV flags backed entirely by database-sourced data — zero LLM hallucination, zero flat bet sizing, strict Kelly Criterion outputs.

## v1 Requirements

### Data Foundation

- [x] **DATA-01**: System stores NFL game, player, and play-by-play data in a PostgreSQL schema with composite indexes on season, week, player_id, and game_id
- [x] **DATA-02**: System ingests multi-season NFL PBP data via nfl_data_py using a year-by-year loading loop with column whitelist and gc.collect() to prevent OOM
- [ ] **DATA-03**: System stores timestamped odds snapshots to PostgreSQL for CLV (closing line value) calculation from day one
- [x] **DATA-04**: System manages schema versioning and migrations via Alembic

### Agent Infrastructure

- [x] **INFRA-01**: System defines a GraphState TypedDict with explicit Annotated reducers for all fields written by multiple agents — no last-write-wins collisions
- [x] **INFRA-02**: System routes queries through a LangGraph Master Router (supervisor) with conditional edges to specialist sub-agents based on request_type
- [x] **INFRA-03**: System defines all Pydantic I/O models (QuantParams, QuantResult, OddsSnapshot, EVSignal, GameState) before any agent logic is written
- [x] **INFRA-04**: System persists LangGraph graph state via SqliteSaver checkpointing from Phase 1, enabling replay on failure

### Quant Engine

- [ ] **QUANT-01**: System enforces a two-stage SQL validation gate — LLM produces a QuantParams Pydantic model, query builder constructs parameterized SQL, LLM never produces raw SQL
- [x] **QUANT-02**: System converts raw sportsbook odds to implied probabilities with configurable vig removal method (multiplicative or Pinnacle sharp)
- [ ] **QUANT-03**: System executes dynamic historical win-rate SQL queries parameterized by game context (weather, opponent, down/distance, situation)
- [x] **QUANT-04**: System simulates historical signal performance via a backtesting module that replays past QuantResult signals against closing lines

### Context & Odds Ingestion

- [x] **CTXT-01**: System ingests live odds asynchronously from The Odds API with a budget manager that tracks per-request cost and enforces a configurable daily API spend cap
- [ ] **CTXT-02**: System rejects any odds payload older than a configurable staleness threshold (default: 5 minutes) before passing to the Arbitrage Agent
- [x] **CTXT-03**: System scrapes qualitative signals (injury reports, weather forecasts) via async Playwright/BeautifulSoup and stores structured binary state changes
- [x] **CTXT-04**: Context Agent updates a global game state JSON on binary state changes (e.g., "Starting QB ruled Out") and propagates the updated state through GraphState

### Risk & Arbitrage Output

- [ ] **ARBT-01**: Arbitrage Agent flags +EV discrepancies by comparing QuantResult true probability against sportsbook implied probability, outputting raw EV percentage and a 3-bullet Trade Plan thesis
- [x] **ARBT-02**: System calculates fractional Kelly Criterion bet sizing based on edge and bankroll parameters — no flat bet sizes are ever output
- [x] **ARBT-03**: CorrelationGuard node enforces hardcoded stops on conflicting market exposures (e.g., Over passing yards + Under total points) before any signal is output
- [x] **ARBT-04**: Aggregator node enforces a daily drawdown gate — if cumulative recommended exposure exceeds the configured limit, no further signals are produced that day

### Kinematic Agent (NFL Alpha)

- [x] **KINE-01**: Kinematic Agent queries NGS tracking data fields (separation at catch point, time-to-throw, press-man coverage rate) from PostgreSQL for matchup-level geometric analysis
- [x] **KINE-02**: Kinematic Agent produces matchup exploit signals based on geometric mismatches (e.g., fast slot WR vs high press-man CB) independent of box score history
- [x] **KINE-03**: System validates NGS field availability by season before Kinematic Agent queries to handle partial coverage years gracefully

### Player Prop Engine (NFL + NBA)

- [x] **PROP-01**: System ingests live NFL and NBA player prop odds (passing/rushing/receiving for NFL; points/rebounds/assists/3PM/PRA for NBA) from The Odds API and writes timestamped `PlayerPropSnapshot` rows to PostgreSQL
- [x] **PROP-02**: System defines `PropParams` and `PropResult` Pydantic models with a two-stage validation gate — LLM produces `PropParams`, `PropQueryBuilder` constructs parameterized SQL, LLM never produces raw SQL or hallucinated stats
- [x] **PROP-03**: System calculates true probability for NFL player props (passing yards/TDs/completions, rushing yards/attempts/TDs, receiving yards/receptions/targets) from historical PostgreSQL distributions with sample size and confidence interval
- [x] **PROP-04**: System incorporates Kinematic Agent signals (separation, press-man coverage rate) into NFL receiving prop probability estimates where NGS data is available
- [ ] **PROP-05**: System calculates true probability for NBA player props (points, rebounds, assists, 3PM, steals, blocks, PRA, double-double) using pace-adjusted historical distributions with opponent defensive rating, rest days, and home/away context
- [ ] **PROP-06**: `PropArbitrageAgent` flags mispriced player props by comparing `PropResult.true_probability` against sportsbook implied probability, outputting raw EV percentage and a 3-bullet Trade Plan thesis with fractional Kelly sizing — no flat bet sizes
- [ ] **PROP-07**: `CorrelationGuard` is extended with a prop conflict matrix that blocks simultaneous correlated prop exposures (e.g., Over passing yards + Under receiving yards on primary target in same game)

### NBA Data Foundation

- [x] **NBA-01**: System ingests NBA player box scores (points, rebounds, assists, 3PM, steals, blocks, minutes) via `nba_api` with a year-by-year loading loop and composite index on season/game/player_id
- [ ] **NBA-02**: System applies pace adjustment, back-to-back rest penalty, and opponent defensive rating weighting to NBA player prop probability distributions

## v2 Requirements

### Synthetic Parlay Builder

- **PARL-01**: System identifies correlated game events (weather + rushing volume + total points) and constructs mathematically sound multi-leg bets
- **PARL-02**: System enforces a minimum N>200 historical sample gate before any correlation coefficient is used in parlay construction
- **PARL-03**: System outputs correlation-adjusted Kelly sizing for multi-leg bets, not naive single-leg Kelly product

### SaaS Frontend

- **FRONT-01**: Next.js terminal UI with dark mode, high-density data tables, and modular widgets for live signal display
- **FRONT-02**: User authentication and session management for multi-user SaaS deployment
- **FRONT-03**: Subscription and billing integration

### Notifications

- **NOTF-01**: System sends push/email alerts when high-confidence +EV signals are flagged above a configurable EV threshold

## Out of Scope

| Feature | Reason |
|---------|--------|
| LLM as stats source | Non-negotiable anti-feature — all numbers must be DB or API sourced |
| Flat bet size recommendations | Non-negotiable — Kelly only |
| Naive parlays without correlation analysis | Financial risk — deferred to v2 with correlation gate |
| NBA game spreads/totals pipeline | Game-level NBA markets deferred; player props addressed in v1 |
| Next.js SaaS terminal | Backend-first; frontend deferred to v2 |
| Cloud deployment / billing | Local dev only for v1 |
| OAuth / user authentication | Single-user local setup for v1 |
| X/Twitter API integration | Rate limits and cost; use scrapers for qualitative signals |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1 | Pending |
| DATA-02 | Phase 1 | Complete |
| DATA-03 | Phase 9 | Pending |
| DATA-04 | Phase 1 | Complete |
| INFRA-01 | Phase 2 | Complete |
| INFRA-02 | Phase 2 | Complete |
| INFRA-03 | Phase 2 | Complete |
| INFRA-04 | Phase 2 | Complete |
| QUANT-01 | Phase 9 | Pending |
| QUANT-02 | Phase 7 | Complete |
| QUANT-03 | Phase 9 | Pending |
| QUANT-04 | Phase 8 | Complete |
| CTXT-01 | Phase 4 | Complete |
| CTXT-02 | Phase 9 | Pending |
| CTXT-03 | Phase 4 | Complete |
| CTXT-04 | Phase 4 | Complete |
| ARBT-01 | Phase 9 | Pending |
| ARBT-02 | Phase 5 | Complete |
| ARBT-03 | Phase 5 | Complete |
| ARBT-04 | Phase 5 | Complete |
| KINE-01 | Phase 6 | Complete |
| KINE-02 | Phase 6 | Complete |
| KINE-03 | Phase 6 | Complete |
| PROP-01 | Phase 10 | Complete |
| PROP-02 | Phase 10 | Complete |
| PROP-03 | Phase 11 | Complete |
| PROP-04 | Phase 11 | Complete |
| PROP-05 | Phase 12 | Pending |
| PROP-06 | Phase 13 | Pending |
| PROP-07 | Phase 13 | Pending |
| NBA-01 | Phase 10 | Complete |
| NBA-02 | Phase 12 | Pending |

**Coverage:**
- v1 requirements: 32 total (23 original + 9 new: PROP-01–PROP-07, NBA-01, NBA-02)
- Mapped to phases: 32
- Unmapped: 0 ✓
- Pending (gap closure phases 9–13): 10 (QUANT-03, QUANT-01, CTXT-02, DATA-03, ARBT-01, PROP-01–PROP-07, NBA-01, NBA-02)

---
*Requirements defined: 2026-03-10*
*Last updated: 2026-03-10 after initial definition*
