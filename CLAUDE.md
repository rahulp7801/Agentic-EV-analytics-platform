# Quant-Sports Agentic Analytics Platform (SaaS)

## Maintained implementation notes

- Shared prop policy now evaluates both Over and Under via the same agent, requires >=20 games, rejects synthetic PrizePicks pricing, and handles integer-line pushes separately. Confidence intervals are dropped when heuristic adjustments change the estimated probability. Missing prop listings no longer imply injuries; historical dates cannot be scanned against live quotes.
- Runtime scanner uses `.checkpoints/analytics.sqlite` for append-only prediction audit and atomic daily recommendation exposure reservations. Repeated scans do not reset the budget; duplicate selections are idempotent and one exposure per player/game prevents correlated/opposite selections. Both graph runtime and scanner share this ledger; in-memory factories remain available for isolated tests. This is recommended exposure, not settled P&L/drawdown.
- Every successfully evaluated scanner selection is audited, including rejected/nonpositive estimates. Ledger reporting deduplicates rescans and supports all-prediction vs accepted-recommendation cohorts, explicit settlements keyed by prediction ID, and last observed pre-game quote CLV. No settled outcomes are inferred from missing data. Prediction IDs are exported to UI cache. CLI: `.venv/Scripts/python.exe -m sportsbet.ledger --settlements outcomes.json`; omit settlements for read-only reporting.
- Fresh recommendations require actual start time and quote age <=5 minutes; DB historical signals are not reused as live quotes. Migrations 0008/0009 preserve prop quote metadata and move ev_signals DDL out of runtime. Backend checks: 87 passed/1 live-DB test skipped, plus 16 scanner/ledger/prop-wiring tests passed including concurrent reservations and restart persistence. Use `--basetemp=.test-tmp-<task>` on this Windows sandbox.


- Evaluation repair: backtests separate model probabilities from entry and closing prices. CLV is raw same-line price-probability movement and requires entry < closing quote < actual start. Replay groups exact outcome/book/line/player identities and keys settlements by entry snapshot ID. Legacy rows without outcome/start metadata are excluded, not guessed. Migration 0007 adds quote identity/start columns; run migrations before ingestion.
- Pending, push, and void settlements are distinct. ROI excludes pending/void stakes; hit rate and Brier/log loss exclude pushes. Brier/log loss and calibration bins use model predictions only, never substitute bookmaker probabilities. Null-model records can still contribute to price and realized-return metrics. Offline replay supports --snapshots-file and --outcomes-file. Backtest/metrics/context tests: 27 passed.

- Make small, verified commits. Do not add assistant co-author/contributor trailers.
- Update this section with important findings and validation as changes land.
- Actual graph nodes are deterministic Python; no LLM API key is currently consumed.
- Windows development: Python can be installed locally with uv; use `.venv/Scripts/python.exe` for tests. `.python/` and `.uv-cache/` are local tooling, not source.
- Runtime imports require both `langgraph` and `langgraph-checkpoint-sqlite`; keep them in `pyproject.toml`.
- Setup verified with workspace Python 3.12 and editable dev install. Initial graph/arbitrage/prop suite: 56 passed, one pre-existing alias test failure (NBA threes/steals/blocks incorrectly classified as NFL). New pricing tests separately reproduce even-money sizing defects.
- Metric names: `ev_percentage`/`ev_pct` are legacy probability edge (percentage points), while `expected_return` is net return per unit staked at the actual payout, including push refunds. Do not label edge as ROI.
- Remaining modeling limitations: defense/pace are neutral placeholders; optional home/rest and NFL kinematic adjustments are unvalidated heuristics and disabled by default. Settled outcomes and timestamped roster/injury history are required to establish predictive performance.
- Pricing correction: actual American price determines break-even, expected return and Kelly. Legacy low-level callers can infer payout from implied probability when raw price is absent. Scanner uses selected prop quotes and the shared agent for both sides; live scans never reuse cached DB sizing.
- Pricing verification: 75 graph, prop, arbitrage, scanner-helper, and pricing tests pass. At p=0.60, quarter Kelly is 0.04 at -110 (previously 0.05) and 0.066667 at +120. Broader context integration tests stalled during external/DB work and were interrupted; do not claim the complete suite passes.
- NBA temporal contract: `PropParams.as_of_date` is an exclusive game-date cutoff. Scanner supplies the target date; NBA graph factory forwards its `target_date` to both context and quant nodes; explicit state `as_of_date` takes precedence, otherwise the NBA agent defaults to today. Historical direct executor callers MUST supply `as_of_date`; undated low-level queries retain legacy season-aggregate behavior.
- Dated NBA probability queries use game logs, including unconditional and double-double queries. Apply the cutoff before the recent-game LIMIT. Empty situational samples broaden to pre-game logs, never season totals; `pregame_fallback` provenance survives context adjustment. Empty history remains insufficient. This removes target/future-game contamination from these queries, but is not a full point-in-time backtester: historical injury/roster snapshots and settled outcomes still need work.
- Removed the offensive-scoring "defensive rating" proxy and its season-total query. Context now uses pre-game logs for rest/home and neutral defense/pace values. Real timestamped team defensive efficiency is still needed; experimental home/rest adjustments remain heuristics and default off.
- Date-cutoff verification: new fixtures first reproduced four failures (future games counted, future recent-game selection, unsafe aggregate fallback, missing agent cutoff). Combined targeted suite now has 120 passing tests. SQL row-selection fixtures execute with SQLite after normalizing PostgreSQL casts; actual PostgreSQL execution and live model accuracy are NOT validated by these tests.

- Frontend uses `/api/signals` to validate freshness/start time/model version/sample/price/stake on every read. Stale, legacy and synthetic prices cannot recommend stakes. UI preserves Under, removes invented confidence intervals and strength ratings, and distinguishes probability edge from expected return. `/api/metrics` reads ledger evaluation with settled/pending/calibration/CLV denominators. Parlay calculator takes an explicit gross payout and reports independence scenarios plus dependence bounds; it no longer claims an optimal joint probability or recommends parlay Kelly stakes.
- Frontend Python routes resolve the workspace `.venv` executable; game-log requests are asynchronous, and scan lock acquisition is exclusive. Existing caches remain visible but gated by freshness during rescans. Node built-in test runner verifies metric semantics (5 tests); TypeScript check and Next.js production build pass. Scan route accepts compact or ISO dates and normalizes to the scanner YYYYMMDD contract. User supplied all three required `.env` keys; settings validation passes but database hostname fails DNS resolution, before authentication. Never print environment values.

- Prop pricing now requires exact player/market/line/side identity and fails closed instead of falling back to game moneyline odds. Scanner evaluates every offered line and Under-only listings, rather than selecting across incomparable lines. Non-push Under confidence intervals complement the reported Over interval; no push-market Under interval is fabricated.
- NFL agents now supply an exclusive as-of cutoff, matching each player's own team/week schedule before taking recent games. NBA/NFL recent windows apply all filters first. NBA teammate absence uses game identity rather than date alone. Unfitted home/rest/pace/kinematic probability adjustments default OFF; enable `EXPERIMENTAL_PROBABILITY_ADJUSTMENTS=true` only for controlled comparisons. Explicit experimental adjustments discard invalidated confidence intervals and do not alter push markets.
- Latest verification: 85 backend tests passed / 1 live-DB skip plus 28 pricing/scanner/wiring tests passed. New executed SQL fixtures cover NFL Thursday-vs-Sunday leakage and NBA last-N home windows; scanner tests cover alternate lines and Under-only listings. The Odds API key passed a read-only catalog check (HTTP 200). All live DB verification remains blocked by DNS. Tests must explicitly opt into a disposable database; never fall back to the user's runtime database.

## 1. System Persona & Project Objective

You are an expert quantitative developer, data engineer, and AI architect. We are building a low-latency, agentic sports analytics platform designed to identify mathematically profitable (+EV) discrepancies in NFL and NBA betting markets.

This is not a simple web scraper. It is a multi-agent orchestration system that treats sports betting exactly like algorithmic futures trading. The system processes unstructured qualitative context (injuries, weather) and heavily structured quantitative data (AWS Next Gen Stats, relational box scores) to execute dynamic probability queries and flag market inefficiencies before retail sportsbooks adjust. The final output is a professional-grade, public-facing SaaS terminal.

## 2. Core Tech Stack

- **Language & Backend:** Python (strictly typed).
- **Agent Orchestration:** LangGraph.
- **Data Validation:** Pydantic (non-negotiable for all LLM outputs).
- **Database:** PostgreSQL (Supabase or local).
- **Data Ingestion:** `nflreadpy` (NFL), asynchronous Playwright/BeautifulSoup scrapers, The Odds API.
- **Frontend:** Next.js / TypeScript.

## 3. The Agentic Architecture (LangGraph Nodes)

The system operates as a directed graph of specialized sub-agents managed by a Master routing node.

- **The Context Agent:** Monitors real-time qualitative streams (X/Twitter APIs, Reddit, RSS). Identifies binary state changes (e.g., "Starting PG is ruled Out") and updates the global game state JSON.
- **The Quant Agent:** The mathematical engine. Constructs and executes dynamic SQL queries against historical data based on the precise parameters defined by the Context Agent.
- **The Arbitrage Agent:** Monitors live odds asynchronously. Compares the Quant Agent's true probability model against implied sportsbook probabilities to flag +EV discrepancies.
- **The Kinematic Agent (NFL Specific):** Queries advanced tracking data (separation, time-to-throw, press-man coverage rates) to find geometric matchup exploits rather than relying on historical box scores.
- **The Synthetic Parlay Builder:** Identifies highly correlated events (e.g., heavy rain + Under passing yards + Over rushing attempts) to build mathematically sound derivative bets.

## 4. Strict Engineering & Coding Standards

### A. Algorithmic Efficiency & State Management

- **Graph Traversal:** The LangGraph state machine must be highly optimized. Treat the agent loop with the strict time-complexity optimization of formal graph algorithms. Avoid infinite loops or redundant node visits.
- **Query Optimization:** We are processing massive, multi-year datasets. SQL queries must use proper indexing. Never use $O(N^2)$ table scans.
- **Memory Management:** When pulling gigabytes of Pandas dataframes via `nflreadpy`, enforce strict memory management. Drop unused columns immediately and utilize Python generators to prevent memory leaks.

### B. Risk Management & Mathematical Rigor (Prop Firm Rules)

- **Never Output Static Bet Sizes:** The system must never recommend a flat monetary bet. It must strictly calculate and output the exact Fractional Kelly Criterion sizing based on the perceived mathematical edge.
- **Capital Preservation:** Treat betting output parameters with the exact same strictness as a funded prop firm's daily drawdown limit.
- **Correlation Hard-Stops:** The agent logic must include hardcoded validation to prevent conflicting market exposures (e.g., advising an Over on passing yards while simultaneously advising an Under on total team points).

### C. LLM Hallucination Prevention

- **Zero Stat Hallucinations:** The LLM is an orchestration engine, not a database. It must never be allowed to guess a player's stats or historical performance. All numbers must be pulled directly from PostgreSQL or the dataframes.
- **Strict Pydantic Typing:** Every single output from an agent that interacts with the database, an API, or the frontend must be strictly typed and validated using Pydantic models. If an agent extracts variables to build a SQL query, it must pass Pydantic validation before the SQL executes.

### D. Frontend UX/UI Philosophy

- **Professional Terminal Interface:** The SaaS frontend must resemble a professional quantitative trading terminal (dark mode, high-density data tables, modular widgets, live data streams). Do not use consumer-style casino/sportsbook UI paradigms.
- **Actionable Theses:** Outputs must include the raw +EV percentage alongside a strict, concise "Trade Plan" thesis (maximum 3 bullet points) explaining the mathematical and contextual logic behind the flagged edge.
