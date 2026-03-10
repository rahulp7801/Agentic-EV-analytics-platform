# Quant-Sports Agentic Analytics Platform

## What This Is

A low-latency, multi-agent sports analytics platform that identifies mathematically profitable (+EV) discrepancies in NFL (and eventually NBA) betting markets. Built on LangGraph, it treats sports betting like algorithmic futures trading — ingesting qualitative context (injuries, weather, social signals) and quantitative data (Next Gen Stats, historical box scores, live odds) to flag market inefficiencies before sportsbooks adjust. The final output is a professional-grade SaaS terminal for quantitative sports analysis.

## Core Value

The Quant Agent must produce statistically grounded +EV flags backed entirely by database-sourced data — zero LLM hallucination, zero flat bet sizing, strict Kelly Criterion outputs.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] LangGraph orchestration graph with Master routing node
- [ ] Context Agent: monitors qualitative signals (injuries, weather, social), updates global game state JSON
- [ ] Quant Agent: builds and executes dynamic SQL queries against historical NFL data via Pydantic-validated parameters
- [ ] Arbitrage Agent: compares Quant Agent's true probability model against live sportsbook odds to flag +EV discrepancies
- [ ] Kinematic Agent (NFL): queries Next Gen Stats tracking data (separation, time-to-throw, press-man coverage) for geometric matchup exploits
- [ ] Synthetic Parlay Builder: identifies correlated events to construct mathematically sound derivative bets
- [ ] Strict Pydantic validation on all LLM outputs before SQL execution
- [ ] Fractional Kelly Criterion sizing output (no flat bet recommendations)
- [ ] Correlation hard-stops (prevent conflicting market exposures)
- [ ] NFL data pipeline via `nfl_data_py` with memory-optimized Pandas usage
- [ ] Odds ingestion via The Odds API
- [ ] PostgreSQL database with proper indexing for multi-year datasets

### Out of Scope

- NBA pipeline — deferred to v2, NFL validated first
- Next.js SaaS terminal — backend-first, frontend deferred
- Cloud deployment / billing — local dev only for v1
- OAuth / user auth — single-user local setup for v1
- Real-time streaming frontend — deferred to post-v1

## Context

- Stack is strictly defined: Python (typed), LangGraph, Pydantic, PostgreSQL (Supabase or local), `nfl_data_py`, Playwright/BeautifulSoup scrapers, The Odds API
- System is modeled on algorithmic trading discipline: prop firm risk rules apply (daily drawdown logic, capital preservation, correlation stops)
- LLM is orchestration only — never a data source. All stats come from PostgreSQL or dataframes
- Frontend paradigm is a professional quant trading terminal (dark mode, high-density, modular widgets) — not a consumer sportsbook UI
- v1 target: local dev, NFL only, backend pipeline fully functional

## Constraints

- **Tech Stack**: Python strictly typed, LangGraph, Pydantic non-negotiable — no deviations
- **Data Integrity**: LLM must never guess stats; all numbers from DB or dataframes
- **SQL Performance**: Proper indexing required; no O(N²) table scans on multi-year datasets
- **Memory**: Drop unused Pandas columns immediately; use generators for large dataframe ops
- **Risk Output**: Kelly Criterion sizing only; no flat bet recommendations ever
- **Correlation**: Hard-coded stops to prevent conflicting market exposures

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LangGraph for orchestration | Directed graph model maps naturally to multi-agent routing; explicit state management | — Pending |
| Pydantic on all LLM outputs | Prevents hallucinated stats from reaching SQL or frontend | — Pending |
| NFL-first, NBA deferred | Validate pipeline on one sport before scaling | — Pending |
| Backend-first, no frontend in v1 | Validate math and data integrity before UX investment | — Pending |
| PostgreSQL over vector DB | Structured historical data benefits from relational queries and indexing | — Pending |

---
*Last updated: 2026-03-09 after initialization*
