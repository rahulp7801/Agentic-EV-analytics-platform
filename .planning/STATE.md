---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 06-02-PLAN.md
last_updated: "2026-03-21T19:18:05.226Z"
last_activity: 2026-03-13 — Phase 3 Plan 01 complete — Quant engine SQL gate, Wilson CI, make_quant_agent closure
progress:
  total_phases: 6
  completed_phases: 6
  total_plans: 18
  completed_plans: 18
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-09)

**Core value:** The Quant Agent must produce statistically grounded +EV flags backed entirely by database-sourced data — zero LLM hallucination, zero flat bet sizing, strict Kelly Criterion outputs.
**Current focus:** Phase 2 - Agent Infrastructure

## Current Position

Phase: 3 of 6 (Quant Engine)
Plan: 1 of 3 in current phase
Status: In progress
Last activity: 2026-03-13 — Phase 3 Plan 01 complete — Quant engine SQL gate, Wilson CI, make_quant_agent closure

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: none yet
- Trend: -

*Updated after each plan completion*
| Phase 01-data-foundation P01 | 16min | 2 tasks | 10 files |
| Phase 01-data-foundation P02 | 18min | 2 tasks | 11 files |
| Phase 01-data-foundation P03 | 9min | 2 tasks | 9 files |
| Phase 02-agent-infrastructure P02 | 20 | 2 tasks | 6 files |
| Phase 02-agent-infrastructure P03 | 6 | 2 tasks | 5 files |
| Phase 03-quant-engine P02 | 5 | 2 tasks | 3 files |
| Phase 03-quant-engine P01 | 7 | 3 tasks | 7 files |
| Phase 03-quant-engine P03 | 3 | 2 tasks | 2 files |
| Phase 04-context-and-odds-ingestion P02 | 12 | 2 tasks | 2 files |
| Phase 04-context-and-odds-ingestion P01 | 15 | 3 tasks | 5 files |
| Phase 04-context-and-odds-ingestion P03 | 15 | 2 tasks | 3 files |
| Phase 04-context-and-odds-ingestion P04 | 3 | 2 tasks | 3 files |
| Phase 05-arbitrage-kelly-and-risk-controls P01 | 4 | 2 tasks | 6 files |
| Phase 05-arbitrage-kelly-and-risk-controls PP02 | 2 | 2 tasks | 3 files |
| Phase 05-arbitrage-kelly-and-risk-controls PP03 | 15 | 2 tasks | 5 files |
| Phase 06-kinematic-agent P01 | 5 | 1 tasks | 7 files |
| Phase 06-kinematic-agent P02 | 4 | 2 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Init]: LangGraph for orchestration — directed graph maps to multi-agent routing
- [Init]: Pydantic on all LLM outputs — prevents hallucinated stats reaching SQL
- [Init]: NFL-first, NBA deferred — validate pipeline on one sport first
- [Init]: Backend-first, no frontend in v1 — validate math before UX investment
- [Phase 01-data-foundation]: Pydantic v2 BaseSettings with ConfigDict — v1 class Config pattern forbidden
- [Phase 01-data-foundation]: src layout with pythonpath=['src'] in pytest config — no editable install required
- [Phase 01-data-foundation]: current_nfl_season() uses date.today() (not datetime.now()) per RESEARCH.md Pitfall 14
- [Phase 01-data-foundation P02]: Hand-written Alembic migration — autogenerate omits composite indexes (Pitfall 4)
- [Phase 01-data-foundation P02]: SPORTSBET_TEST_DATABASE_URL gates DB tests with skipif — not xfail — for real assertions
- [Phase 01-data-foundation P02]: SET enable_seqscan=off in EXPLAIN test — reliable at any row count including empty table
- [Phase 01-data-foundation P02]: press_man_rate nullable in ngs_stats — forward-compatible for Phase 6 per RESEARCH.md open question
- [Phase 01-data-foundation P02]: asyncpg pool for hot-path agent queries; psycopg engine for bulk ingestion/migrations
- [Phase 01-data-foundation]: nflreadpy over nfl_data_py: archived Sep 2025; all ingestion uses import nflreadpy as nfl — no import nfl_data_py in src/
- [Phase 01-data-foundation]: Polars-first write path: nflreadpy returns Polars; .to_pandas() called only before to_sql() — minimizes pandas memory footprint per season
- [Phase 01-data-foundation]: site-packages in pytest pythonpath: Windows pip --target workaround; pythonpath = ['src', 'site-packages'] in pyproject.toml
- [Phase 02-agent-infrastructure P01]: Annotated + Field constraints (ge/le/gt/max_length) preferred over @field_validator for simple range guards — less boilerplate, same enforcement
- [Phase 02-agent-infrastructure P01]: QuantResult all-nullable stub design — Phase 2 stub nodes return QuantResult() without DB access; Phase 3 populates real values
- [Phase 02-agent-infrastructure P01]: AgentOddsSnapshot.implied_probability is Decimal not int — conversion from American odds happens at ingestion time to prevent unit-mismatch bugs
- [Phase 02-agent-infrastructure P01]: EVSignal.kelly_fraction hard cap 0.25 enforced at model level (Decimal Field constraint) — matches CLAUDE.md fractional Kelly prop firm rule
- [Phase 02-agent-infrastructure]: Stub agents return partial dicts (not full GraphState) — LangGraph merges via reducers; correct LangGraph partial state update pattern
- [Phase 02-agent-infrastructure]: route_from_master (conditional edge fn) handles routing; master_router node is pure passthrough — matches LangGraph API separation of concerns
- [Phase 02-agent-infrastructure]: No checkpointer in Plan 02-02 — Plan 02-03 adds AsyncPostgresSaver after graph skeleton validated
- [Phase 02-agent-infrastructure]: AsyncSqliteSaver required for async graph.ainvoke() — sync SqliteSaver raises NotImplementedError on aget_tuple()
- [Phase 02-agent-infrastructure]: create_graph_with_sqlite() is async — must be awaited; bankroll_usd and max_kelly_fraction live in Settings not GraphState
- [Phase 03-quant-engine]: Power devig binary search range is [1, 20] not (0, 1] — for p in (0,1), p^k < p when k>1, so overround normalization requires k>1
- [Phase 03-quant-engine]: Multiplicative sum-to-one achieved via residual correction on last element — eliminates Decimal division remainder
- [Phase 03-quant-engine]: ALLOWED_FILTER_KEYS frozenset is structural SQL injection prevention — column names never user-supplied; values always in asyncpg $N positional params
- [Phase 03-quant-engine]: Decimal(str(round(x,6))) wrapping for Wilson CI bounds — statsmodels float rejected by QuantResult strict=True; never assign float to Decimal field
- [Phase 03-quant-engine]: MIN_SAMPLE_SIZE=30 gate returns QuantResult(data_source='insufficient_sample', true_probability=None) — callers must handle None probability before Kelly sizing
- [Phase 03-quant-engine]: make_quant_agent(pool) closure factory pattern — pool injected at construction time; sync stub quant_agent preserved for Phase 2 backward-compat when quant_node=None
- [Phase 03-quant-engine]: BacktestEngine standalone offline module — never imported from graph.py or any agent node; isolation documented in module docstring and enforced by plan must_have
- [Phase 03-quant-engine]: closing_line_note as BacktestReport field — makes pre-game snapshot constraint (snapshot_time < game_start_time is caller's responsibility) machine-readable to callers, not just docstring
- [Phase 04-context-and-odds-ingestion]: httpx.AsyncClient entered via internal __aenter__() inside OddsAPIPoller so patch() correctly intercepts client instance for unittest.mock
- [Phase 04-context-and-odds-ingestion]: _credits_remaining in-memory only in v1; WARNING logged on restart; persistent budget tracking deferred to Phase 5
- [Phase 04-context-and-odds-ingestion]: is_stale() raises TypeError on naive datetime — enforces UTC-awareness at API boundary
- [Phase 04-context-and-odds-ingestion]: down_revision in 0002 must be '0001' (not '0001_initial_schema') — actual revision ID in migration file is the short form
- [Phase 04-context-and-odds-ingestion]: ContextSignals imported directly in state.py (not TYPE_CHECKING guard) — no circular dependency exists between graph/models.py and graph/state.py
- [Phase 04-context-and-odds-ingestion]: MagicMock (not AsyncMock) for pool.acquire in test — AsyncMock makes acquire() return a coroutine which breaks async with pool.acquire() as conn pattern
- [Phase 04-context-and-odds-ingestion]: ContextSignals imported at runtime in state.py (not TYPE_CHECKING) — LangGraph calls get_type_hints(GraphState) which cannot resolve forward refs for TYPE_CHECKING-only imports
- [Phase 04-context-and-odds-ingestion]: Weather scraping (Playwright/NFLWeather.com) deferred to v2 — Context Agent accepts weather_json=None in v1; keeps scraper.py focused and testable
- [Phase 04-context-and-odds-ingestion]: make_context_agent closure factory: pool, api_key, daily_credit_cap injected at construction; sync stub context_agent preserved as fallback when context_node=None
- [Phase 04-context-and-odds-ingestion]: BudgetExhaustedError caught inside make_context_agent closure returning ContextSignals(odds_snapshot=None) — never propagates exception to LangGraph
- [Phase 04-context-and-odds-ingestion]: _extract_odds_snapshot uses Decimal(str(round(raw_prob, 6))) for American odds conversion — prevents float assigned to strict Pydantic Decimal field
- [Phase 05-arbitrage-kelly-and-risk-controls]: make_arbitrage_agent takes optional settings_override (not pool) — arbitrage math is stateless; no DB access needed
- [Phase 05-arbitrage-kelly-and-risk-controls]: compute_ev_percentage = true_prob - implied_prob, floored at 0 — simplest correct positive-edge definition before devig
- [Phase 05-arbitrage-kelly-and-risk-controls]: asyncio.run() replaces deprecated asyncio.get_event_loop().run_until_complete() in test_quant.py — prevents event loop conflict on Python 3.12
- [Phase 05-arbitrage-kelly-and-risk-controls]: CONFLICT_PAIRS hardcoded at module level as frozenset[frozenset[str]] — immutable, O(1) membership test, extensible without touching CorrelationGuard class
- [Phase 05-arbitrage-kelly-and-risk-controls]: Aggregator gate-on-limit: triggering signal blocked and NOT counted in cumulative — conservative prop-firm daily hard stop interpretation
- [Phase 05-arbitrage-kelly-and-risk-controls]: No LangGraph coupling in Plan 02 risk controls — CorrelationGuard and Aggregator are pure Python; graph wiring deferred to Plan 03
- [Phase 05-arbitrage-kelly-and-risk-controls]: make_correlation_guard_node and make_aggregator_node in graph.py (not agents.py) — graph-layer orchestration wrapping stateful risk objects
- [Phase 05-arbitrage-kelly-and-risk-controls]: Aggregator instance created at graph construction time — persists cumulative exposure across ainvoke calls within same process, models daily gate correctly
- [Phase 05-arbitrage-kelly-and-risk-controls]: arbitrage_analysis request_type routes to arbitrage_agent alongside odds_check — cleaner semantic for direct Phase 5 pipeline invocation
- [Phase 06-kinematic-agent]: KinematicParams.season uses Field(ge=2016) not ge=1999 — NGS data boundary enforced at Pydantic layer before any DB query
- [Phase 06-kinematic-agent]: press_man_rate=None always on KinematicAnalysis — column is NULL in all current ngs_stats rows; forward-compat only; never queried
- [Phase 06-kinematic-agent]: kinematic_result: Optional[KinematicAnalysis] added to GraphState at runtime import (not TYPE_CHECKING) — follows Phase 4 ContextSignals import pattern for LangGraph get_type_hints() compatibility
- [Phase 06-kinematic-agent]: _kinematic_stub defined inline in create_graph() body — co-located with usage, avoids module namespace pollution
- [Phase 06-kinematic-agent]: kinematic_agent -> END edge: independent pipeline, no coupling to arbitrage/quant nodes

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2 RESOLVED]: LangGraph 1.1.0 with langgraph-checkpoint-sqlite-3.0.3 installed. AsyncSqliteSaver used (not AsyncPostgresSaver — SQLite sufficient for Phase 2 checkpointing)
- [Phase 4]: Verify current Odds API sport key naming and rate limits against live API documentation before implementing polling loop
- [Phase 6]: Verify nfl_data_py NGS field availability for current seasons before designing Kinematic Agent queries

## Session Continuity

Last session: 2026-03-21T19:14:31.515Z
Stopped at: Completed 06-02-PLAN.md
Resume file: None
