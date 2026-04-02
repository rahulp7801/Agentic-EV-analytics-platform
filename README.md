# Quant-Sports Agentic Analytics Platform

A low-latency, multi-agent sports analytics platform designed to identify mathematically profitable (+EV) discrepancies in NBA (and NFL) prop betting markets. Built like an algorithmic trading desk — not a sportsbook UI.

---

## Overview

The system treats sports betting exactly like a prop trading firm treats financial markets. It ingests structured quantitative data (historical player stats, defensive ratings, rest/travel context) and qualitative signals (injury reports, roster availability), runs them through a LangGraph agent pipeline, and outputs Fractional Kelly-sized +EV signals with full mathematical justification.

**What makes this different from a typical betting tool:**
- All stat values come from PostgreSQL — the LLM never guesses a number
- Every agent output is Pydantic-validated before executing SQL or emitting signals
- EV is capped at 15% and gated by minimum sample size — no degenerate signals
- Kelly sizing is fractional and conditional on true edge, not flat bet recommendations
- The frontend resembles a quant trading terminal, not a casino UI

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    scan_game_ev.py                          │
│  CLI entry point — orchestrates the full pipeline per game  │
└────────────────────────┬────────────────────────────────────┘
                         │
          ┌──────────────▼───────────────┐
          │     LangGraph State Machine   │
          │  (src/sportsbet/graph/)       │
          └──┬────────┬────────┬─────────┘
             │        │        │
    ┌────────▼─┐ ┌────▼────┐ ┌▼──────────────┐
    │  Context  │ │  Quant  │ │  Arbitrage    │
    │  Agent    │ │  Agent  │ │  Agent        │
    │           │ │         │ │               │
    │ Roster    │ │ SQL over │ │ EV = model_p  │
    │ inactives │ │ hist.    │ │ - implied_p   │
    │ teammate  │ │ gamelogs │ │ Kelly sizing  │
    │ context   │ │         │ │               │
    └──────────┘ └─────────┘ └───────────────┘
             │
    ┌────────▼──────────────────────────────┐
    │  PostgreSQL (Supabase)                │
    │  nba_player_stats | nba_game_logs     │
    │  player_prop_snapshots | ev_signals   │
    │  games                                │
    └───────────────────────────────────────┘
```

### Agent Roles

| Agent | Responsibility |
|---|---|
| **Context Agent** | Identifies inactive teammates from ESPN roster. Calculates rest days, home/away, opponent defensive rating. Builds `NBAContext` for each player. |
| **Quant Agent** | Runs parameterized SQL over `nba_game_logs` with situational filters (opponent quality, rest, teammate availability). Returns `PropAnalysis` with distribution stats. |
| **Arbitrage Agent** | Computes `EV = true_prob - implied_prob`. Applies goblin-line filter, 15% EV cap, minimum sample gate. Outputs `EVSignal` with Fractional Kelly stake. |
| **NBA Executor** | Orchestrates the per-player graph run. Applies 50% shrinkage toward season mean for small samples. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12, strictly typed |
| Agent Orchestration | LangGraph |
| Data Validation | Pydantic v2 (all LLM/agent outputs) |
| Database | PostgreSQL via Supabase |
| Async DB Client | asyncpg (with Windows IPv4 pooler fix) |
| Sync DB / Migrations | SQLAlchemy 2.0 + Alembic |
| Prop Data | The Odds API → PrizePicks → ESPN (cascade) |
| NBA Stats Ingestion | `nba_api`, `nflreadpy`, BallDontLie API |
| Frontend | Next.js / TypeScript |
| LLM Backend | Claude (Anthropic) via LangGraph tool nodes |

---

## Project Structure

```
sportsbet/
├── scan_game_ev.py          # Main EV scanner — run this per game
├── predict.py               # Standalone prop prediction CLI
├── ingest_2025.py           # NBA game log ingestion (2024-25 season)
├── ingest_stats_2025.py     # Season aggregate stats ingestion
│
├── src/sportsbet/
│   ├── config.py            # Settings (DATABASE_URL, API keys via pydantic-settings)
│   ├── db/
│   │   ├── connection.py    # asyncpg pool factory (Windows IPv4 pooler fix)
│   │   └── models.py        # SQLAlchemy ORM models (5 tables)
│   ├── graph/
│   │   ├── graph.py         # LangGraph state machine definition
│   │   ├── state.py         # GraphState TypedDict
│   │   ├── router.py        # Conditional edge routing
│   │   └── agents.py        # Generic agent node wrappers
│   ├── prop/
│   │   ├── nba_agents.py    # Context + Quant agent implementations
│   │   ├── nba_executor.py  # Per-player graph orchestrator
│   │   ├── nba_context_producer.py  # NBAContext builder (rest, def rating, roster)
│   │   ├── arbitrage.py     # EV calculation + Kelly sizing + signal emission
│   │   └── nba_query_builder.py    # Parameterized SQL builder for game logs
│   ├── ingestion/
│   │   ├── nba.py           # nba_api game log fetcher
│   │   ├── nba_gamelogs.py  # Bulk gamelog ingestion pipeline
│   │   ├── free_odds.py     # PrizePicks + ESPN props pollers
│   │   ├── prop_odds.py     # The Odds API player props fetcher
│   │   ├── odds_poller.py   # Live odds polling loop
│   │   └── player_stats.py  # Season aggregate stats
│   └── quant/
│       ├── vig.py           # Vig removal + implied probability
│       └── backtest.py      # Historical EV backtesting framework
│
├── frontend/                # Next.js terminal UI
│   ├── app/                 # App Router pages
│   └── components/
│       ├── Arbitrage.tsx    # Main EV scanner tab (run scan, view signals)
│       ├── EVDashboard.tsx  # Signal history + aggregate view
│       ├── PropsAnalysis.tsx
│       ├── GameLogs.tsx
│       ├── ParlayBuilder.tsx
│       └── KellyCalc.tsx
│
├── alembic/                 # DB migrations
├── tests/
└── pyproject.toml
```

---

## Database Schema

| Table | Purpose |
|---|---|
| `games` | Game metadata (teams, date, weather) |
| `nba_player_stats` | Season aggregate stats — player lookup by name |
| `nba_game_logs` | Per-game box scores with situational context (opponent, home/away, rest days) |
| `player_prop_snapshots` | Raw prop lines fetched from Odds API / PrizePicks |
| `ev_signals` | Computed EV signals with Kelly sizing, persisted per scan |

Key indexes: `(player_id, season)`, `(game_date, opponent_team)`, `(player_id, game_date)` — all queries use index scans, no full-table scans.

---

## Setup

### Prerequisites

- Python 3.12+
- Node.js 18+ (for frontend)
- PostgreSQL database (Supabase recommended)
- The Odds API key (free tier: 500 credits/month)

### 1. Install Python dependencies

```bash
pip install -e ".[dev]"
```

### 2. Configure environment

Create `.env` in the project root:

```env
# Database — use the Supabase SESSION POOLER URL on Windows (IPv4 required)
# Get from: Supabase Dashboard → Project Settings → Database → Connection Pooling
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
DATABASE_URL_ASYNC=postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres

# The Odds API — https://the-odds-api.com
ODDS_API_KEY=your_key_here

# Anthropic (for LangGraph agent LLM calls)
ANTHROPIC_API_KEY=your_key_here
```

> **Windows note:** The Supabase direct host (`db.<ref>.supabase.co`) is IPv6-only and will fail on Windows. Use the session pooler URL above. The `connection.py` auto-detects and rewrites the URL if you forget.

### 3. Run database migrations

```bash
alembic upgrade head
```

### 4. Ingest NBA data

```bash
# Ingest 2024-25 game logs (~2,500 games)
python ingest_2025.py

# Ingest season aggregate stats (for player ID lookup)
python ingest_stats_2025.py
```

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000`.

---

## Running the EV Scanner

```bash
# Scan a specific game for today
python scan_game_ev.py --team-a OKC --team-b LAL

# Specify a date (YYYYMMDD)
python scan_game_ev.py --team-a GSW --team-b BOS --date 20260410

# Force re-scan (bypass DB cache)
python scan_game_ev.py --team-a OKC --team-b LAL --force
```

**What the scanner does:**

1. Verifies the matchup exists on ESPN's schedule
2. Fetches rosters from ESPN — identifies likely inactive players
3. Fetches prop lines: Odds API → PrizePicks → ESPN (cascade fallback)
4. For each player on the prop slate, runs the LangGraph pipeline:
   - Queries historical game logs conditioned on inactive teammates
   - Computes model probability using normal distribution over historical mean
   - Applies defensive rating, home/away, and rest-day adjustments
   - Calculates EV and Fractional Kelly stake
5. Writes results to `frontend/public/signals_cache.json` (live-loaded by UI)
6. Persists signals to `ev_signals` table in PostgreSQL

**Signal output example:**

```
Shai Gilgeous-Alexander  ASSISTS U6.5
  EV:          +5.2%
  Model prob:  57.3%
  Implied:     52.2%
  Kelly stake: 2.7% of bankroll
  Sample:      62 games | mean 6.6
  Trade Plan:
    - +5.2% EV edge on assists UNDER 6.5 | n=62 games, mean=6.6 historical
    - Context: opp def 93.7 < avg 115 (strong D) | 2d rest | HOME | conditioned on Barnhizer, Carlson inactive
    - Kelly: 2.7% bankroll stake (fractional, not flat) | No material injury flags
```

---

## EV Model Details

### Probability Estimation

For each prop, the model estimates `P(stat < line)` using a normal distribution fit to the player's conditional game log sample:

```
model_prob = Φ((line - μ_conditional) / σ_conditional)
```

Where:
- `μ_conditional` = mean stat in games matching situational filters (opponent tier, rest, teammate availability)
- `σ_conditional` = std dev from same sample
- 50% shrinkage toward season mean is applied for samples < 30 games

### Adjustments

| Factor | Effect |
|---|---|
| Strong defense (opp_def_rtg < avg) | Suppresses model probability for Over; boosts Under |
| Home game | +1.5pp to model probability for Over props |
| Back-to-back (0 rest days) | Flagged as fatigue risk — noted in trade plan |
| Key teammate inactive | Conditions the historical sample to matching games only |

### Risk Controls

- **15% EV cap** — signals above this threshold are suppressed (likely data artifacts)
- **Goblin line filter** — PrizePicks "easy" lines (implied prob < 40% for Under) are excluded
- **Minimum sample gate** — signals with < 15 conditional games are marked `[GATED]` and excluded from Kelly sizing
- **Correlation hard-stop** — conflicting Over/Under signals on correlated markets for the same player are deduplicated

### Kelly Sizing

```
f* = edge / odds_decimal  (Fractional Kelly at 50% of full Kelly)
```

Output is always a percentage of bankroll, never a flat dollar amount.

---

## Prop Data Sources

| Source | Status | Notes |
|---|---|---|
| The Odds API | Active | Primary source. ~1 credit/event. Free tier: 500 credits/month |
| PrizePicks | Blocked | HTTP 403 (PerimeterX bot protection as of 2026-03) |
| ESPN Core API | Fallback | No vig/odds data — lines only. Less reliable than Odds API |
| DraftKings | Blocked | HTTP 403 |

---

## Frontend

The terminal UI is built with Next.js (App Router) and uses a dark, high-density data layout. No casino UI paradigms.

**Tabs:**
- **Dashboard** — Aggregate signal history, win rate stats
- **Arbitrage** — Run live scans, view current +EV signals per game
- **Props Analysis** — Browse raw prop lines by player/market
- **Game Logs** — Query historical situational game logs
- **Parlay Builder** — Construct correlated-event synthetic parlays
- **Kelly Calculator** — Standalone bankroll sizing tool

---

## Engineering Notes

### Windows / asyncpg

The `WindowsSelectorEventLoopPolicy` is required for asyncpg's SSL. The Supabase direct host resolves to IPv6-only; the session pooler resolves to IPv4. `db/connection.py` auto-detects `db.<ref>.supabase.co` hostnames and rewrites them to `aws-0-<region>.pooler.supabase.com:5432` with the correct `postgres.<ref>` username format.

### LLM Guardrails

The LLM layer (Claude via LangGraph tool nodes) is an **orchestration engine only** — it constructs queries and interprets results, but never generates or hallucinates stat values. All numbers are pulled from PostgreSQL and passed to the LLM as structured context. Every agent output is Pydantic-validated before SQL execution.

### Query Design

All hot-path queries use index-covered lookups on `(player_id, season)` and `(player_id, game_date)`. The conditional game log query (`nba_query_builder.py`) filters on opponent defensive rating tier and rest days at the SQL level — no post-hoc Python filtering.

---

## License

Private — all rights reserved.
