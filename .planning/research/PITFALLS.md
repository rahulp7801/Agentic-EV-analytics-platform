# Domain Pitfalls

**Domain:** Quant sports betting analytics — LangGraph multi-agent, NFL data pipeline, Pydantic validation, Kelly Criterion
**Researched:** 2026-03-09
**Confidence note:** All external research tools were denied in this session. Findings are drawn from training knowledge (cutoff August 2025). Claims about specific library APIs are MEDIUM confidence unless otherwise noted. Operational/mathematical claims are HIGH confidence.

---

## Critical Pitfalls

Mistakes that cause rewrites, data corruption, financial misjudgment, or silent failures.

---

### Pitfall 1: LLM as Implicit Data Source (Hallucinated Stats Reach SQL)

**What goes wrong:** A LangGraph node asks the LLM to "fill in" missing context, and the LLM fabricates a plausible-sounding stat (e.g., a player's completion percentage, injury status, or historical win rate). That value is then serialized into a Pydantic model, passes validation because it is structurally valid, and gets written to PostgreSQL or used in an EV calculation. The system produces confident-looking output from invented data.

**Why it happens:** LLM nodes are easy to write; DB query nodes require schema knowledge and more boilerplate. Under time pressure, developers add "just ask the LLM" shortcuts. Pydantic validates shape, not provenance — a hallucinated `float` is indistinguishable from a real one.

**Consequences:** Every downstream calculation (Kelly sizing, EV flag, parlay correlation) is silently poisoned. Backtests look valid because the hallucinated data is internally consistent. Real bets are sized on fabricated numbers.

**Prevention:**
- Enforce a hard architectural rule at the graph level: LLM nodes have write access ONLY to qualitative fields (injury narratives, weather context, sentiment signals). Quantitative fields must be `None` or raise a validation error if the LLM touches them.
- Add a `data_source` annotation field to all Pydantic models carrying stats: `Literal["db", "dataframe", "api"]`. Any value not from an approved source is rejected before state update.
- Write a graph-level pre-commit hook that inspects state diffs after each LLM node and asserts no numeric stat fields changed.

**Detection (warning signs):**
- Stat values appear in state that cannot be traced to a DB query ID or dataframe row index in the run log.
- LLM node outputs contain specific numeric values (percentages, yardage, counts) in natural language rather than structured references.
- Backtests produce suspiciously smooth win-rate curves — hallucinated data tends to be "reasonable" and reduces variance artificially.

**Phase:** Address in Phase 1 (core graph architecture). Non-negotiable before any agent node is written.

---

### Pitfall 2: Kelly Criterion Applied to Non-Independent Events (Correlation Blindness)

**What goes wrong:** Full Kelly or even fractional Kelly is applied to a set of bets that share correlated outcomes — e.g., betting Patrick Mahomes passing yards AND the Chiefs moneyline in the same game, or two props that both resolve on weather affecting a single game. The bets appear independent by market type but are highly correlated. The Kelly formula assumes independent trials; applying it to correlated events systematically over-sizes the book and destroys the bankroll in correlated loss scenarios.

**Why it happens:** Kelly is usually implemented bet-by-bet. Multi-position portfolio-level correlation checks are harder to implement and easy to skip. The mistake is invisible until a correlated loss event hits.

**Consequences:** A single bad weather game, a star player DNP, or a one-sided blowout wipes out multiple simultaneously open positions at once — all sized as if they were independent.

**Prevention:**
- Before any Kelly size is emitted, run a correlation matrix check against all currently open positions. Use a configurable threshold (e.g., `r > 0.4` on historical co-movement of the prop types).
- Implement correlation hard-stops as a graph node, not a post-processing step. The Arbitrage Agent must pass through a `CorrelationGuard` node before outputting any bet recommendation.
- For same-game parlays or same-player multi-props, treat the entire bundle as a single Kelly position — size the bundle, not each leg independently.
- Store correlation coefficients in PostgreSQL and update them after each NFL week, not just at build time.

**Detection:**
- Multiple open positions share the same game ID, same player ID, or the same weather-sensitive venue.
- Recommended positions sum to Kelly fractions exceeding 0.25 of bankroll in a single week's slate.
- Backtests show rare but catastrophic drawdown events that wipe 30%+ of bankroll in a single slate.

**Phase:** Address in Phase 2 (Arbitrage Agent and Kelly sizing). Must be in place before any live odds integration.

---

### Pitfall 3: LangGraph Shared State Mutation — Reducer Conflicts and Lost Writes

**What goes wrong:** Multiple agents in a LangGraph graph update the same state key without a proper reducer. LangGraph's default behavior for state keys without a reducer is last-write-wins. When two agents run concurrently (e.g., Context Agent and Quant Agent both write to `game_state`), one write silently overwrites the other. The losing agent's updates are permanently lost with no error raised.

**Why it happens:** LangGraph's `TypedDict` state definition looks like a plain dict. Developers assume it works like a dict — it does not. Without explicit `Annotated[list, operator.add]` or custom reducer annotations, concurrent writes clobber each other. This is easy to miss when agents are developed and tested sequentially but run concurrently in production.

**Consequences:** Context Agent injury flags are overwritten by Quant Agent's state write, causing the Quant Agent to reason without injury context. Or vice versa — stale qualitative context persists while quantitative values update. The system appears to function but is reasoning from incomplete state.

**Prevention:**
- Define all shared state keys with explicit reducers from day one, even when initially running agents sequentially. Use `Annotated[T, reducer_fn]` for every field that more than one agent touches.
- Separate agent-owned state namespaces within the global state: `context_agent_state`, `quant_agent_state`, `arbitrage_agent_state`. Only the owning agent writes its namespace. A final aggregation node merges namespaces into a read-only shared context.
- Write a state schema test that runs all agents concurrently against a fixture and asserts all expected keys are present and non-None after the run.

**Detection:**
- State inspection after a run shows keys that should have been updated are `None` or carry values from a previous run.
- Adding logging to each state write reveals two agents writing the same key within the same graph step.
- Tests pass sequentially but fail under `asyncio.gather` parallelism.

**Phase:** Address in Phase 1 (graph architecture). Define the state schema and reducer strategy before writing any agent node.

---

### Pitfall 4: nfl_data_py Full Season Load into Memory — OOM on Multi-Year Queries

**What goes wrong:** `nfl_data_py.import_pbp_data([2018, 2019, 2020, 2021, 2022, 2023])` loads all play-by-play data for all requested seasons into a single Pandas DataFrame. Each NFL season's PBP data is roughly 45,000-60,000 rows × 372 columns. Loading 6 seasons simultaneously can consume 4-8 GB of RAM before any processing begins. On a development machine with other processes running, this causes OOM kills or severe swap thrashing that makes the pipeline appear to hang.

**Why it happens:** The `nfl_data_py` API is ergonomic — a single function call returns everything. Developers load what they need for analysis without considering memory footprint. The problem is invisible on small queries and only manifests on multi-year historical loads.

**Consequences:** Pipeline silently crashes or produces partial results. If the OOM happens after partial DB writes, the PostgreSQL tables are in an inconsistent state. Re-running without cleanup creates duplicate rows.

**Prevention:**
- Never load more than two seasons simultaneously. Loop year-by-year: load one season, select only required columns, write to PostgreSQL, call `del df; gc.collect()` before loading the next.
- Define a required-columns whitelist per data type (PBP, player stats, schedules). Drop all other columns immediately after `import_pbp_data` returns, before any further processing.
- Use chunked PostgreSQL writes (`df.to_sql(..., chunksize=1000, if_exists='append')`) rather than writing the full DataFrame at once.
- Add a memory guard: log `psutil.virtual_memory().percent` before and after each season load. Abort if usage exceeds 80%.

**Detection:**
- Process is killed by the OS without a Python exception (OOM kill appears in system logs, not application logs).
- `import_pbp_data` call hangs for >120 seconds on multi-year queries.
- PostgreSQL tables have duplicate rows after a re-run — evidence of a partial write followed by a restart.

**Phase:** Address in Phase 1 (data pipeline). The ingestion architecture must be column-selective and year-by-year before any data is loaded.

---

### Pitfall 5: Pydantic v2 Validator Semantics — Silent Validation Bypass

**What goes wrong:** Code written with Pydantic v1 patterns (`@validator`, `@root_validator`) is imported into a Pydantic v2 environment. Pydantic v2 ships with a v1 compatibility shim that accepts these decorators without raising an import error, but the validation behavior changes in subtle ways: `@validator` runs after field assignment by default in v1, but the v2 shim may not enforce `always=True` correctly; `@root_validator(pre=True)` semantics differ from `@model_validator(mode='before')`. The result is that validators appear to work in unit tests but silently pass invalid data in edge cases.

**Why it happens:** The compatibility layer hides the migration need. `pip install pydantic>=2` does not force any code changes. CI passes because unit tests use happy-path inputs that both v1 and v2 validate identically. Edge cases — null fields, unexpected types from LLM outputs — hit the divergent code paths.

**Consequences:** An LLM output with a `None` where a `float` is expected passes the validator (because the v1-style `always=False` default skips validation on `None`), gets stored in state, and reaches the Kelly formula where `None * bankroll` raises a `TypeError` at runtime — or worse, if downstream code handles `None` gracefully, an EV of `None` is silently treated as 0 or skipped.

**Prevention:**
- Pin to Pydantic v2 from day one. Use `pydantic>=2.0,<3.0` in `pyproject.toml`. Never rely on the v1 compatibility shim.
- Use only native v2 patterns: `@field_validator` with `@classmethod`, `@model_validator(mode='before'|'after')`. Never import `validator` or `root_validator`.
- For all LLM output models, set `model_config = ConfigDict(strict=True)`. This prevents coercion of strings to floats, which hides type mismatches from LLM-generated JSON.
- Write a test fixture that passes intentionally malformed LLM output (extra fields, wrong types, `None` for required numerics) and asserts `ValidationError` is raised for each case.

**Detection:**
- `from pydantic import validator` imports succeed without deprecation warnings (means shim is active).
- Unit tests pass but integration tests with real LLM output fail with `TypeError` or `AttributeError` on numeric fields.
- Running `python -c "import pydantic; print(pydantic.VERSION)"` returns `2.x` but codebase still contains `@validator` decorators.

**Phase:** Address in Phase 1 (foundation). All Pydantic models must be written in native v2 syntax before any agent node is built on top of them.

---

### Pitfall 6: The Odds API Rate Limiting and Stale Odds Windows

**What goes wrong:** The Odds API free tier allows 500 requests/month; paid tiers are usage-based. A naively written polling loop checking odds every 60 seconds during a full NFL Sunday (16 games × 10+ markets each) burns through API quota in minutes. More critically, odds ingested 5+ minutes before game time are stale — lines move rapidly in the final hour pre-kickoff. Stale odds make EV calculations appear positive when the real-time line has already closed the gap.

**Why it happens:** Developers write a polling loop during development against a small fixture (1-2 games) and only discover quota exhaustion when running against a full slate. The stale-odds problem is invisible in backtesting because historical data is used — the real-time latency problem only appears in live operation.

**Consequences:** Quota exhaustion means no odds data for the rest of the month. Stale odds cause false positive EV flags — the Arbitrage Agent recommends a bet that the sportsbook line has already corrected, resulting in a bet at a negative-EV price.

**Prevention:**
- Implement a request budget manager from day one: track requests made this billing period against a configurable cap. Warn at 70%, hard-stop at 90% to preserve a buffer for critical lookups.
- Cache odds responses with a configurable TTL (e.g., 5 minutes for non-game-day, 60 seconds within 2 hours of kickoff). Store cache in PostgreSQL or Redis with `fetched_at` timestamp.
- Before any EV calculation, assert `odds_age_seconds < MAX_STALE_THRESHOLD` (configurable, default 300 seconds). If stale, re-fetch or discard the analysis rather than proceeding.
- Use The Odds API's `bookmakers` filter to request only the sportsbooks relevant to the user's jurisdiction — reduces response size and counts.

**Detection:**
- HTTP 429 responses from The Odds API.
- `remaining_requests` field in API response headers drops rapidly during a full-slate polling run.
- EV flags appear for games where odds were last fetched >10 minutes ago.

**Phase:** Address in Phase 2 (live odds ingestion). The caching and budget manager must be built before any live polling loop runs against the real API.

---

### Pitfall 7: PostgreSQL Missing Composite Indexes — Full Table Scans on Multi-Year Queries

**What goes wrong:** The PBP table has 250,000+ rows (5+ years of NFL play-by-play). A query like `WHERE season = 2023 AND week = 14 AND posteam = 'KC' AND play_type = 'pass'` against an unindexed table does a sequential scan. On a development machine, this is slow (2-10 seconds). Inside a LangGraph agent node that may be called dozens of times per analysis run, it becomes a bottleneck. The Quant Agent's dynamic SQL queries, which combine multiple filter conditions, are particularly sensitive.

**Why it happens:** Developers create tables with `nfl_data_py` data and a primary key index, then start querying before adding domain-specific indexes. The slow queries are not noticed during development with small datasets but become unacceptable with full historical data.

**Consequences:** Analysis runs that should complete in seconds take minutes. The LangGraph graph times out or the LLM context window fills with latency while waiting for DB results.

**Prevention:**
- Define indexes in the schema migration scripts before loading any data. Required composite indexes for PBP: `(season, week)`, `(posteam, season)`, `(defteam, season)`, `(play_type, season, week)`, `(passer_player_id, season)`, `(receiver_player_id, season)`.
- Add `EXPLAIN ANALYZE` output to the CI test suite for the 10 most common Quant Agent query patterns. Assert that no query uses `Seq Scan` on tables with >10,000 rows.
- Use `BRIN` indexes (block range indexes) on the `game_date` column — more efficient than B-tree for ordered time-series data.

**Detection:**
- `EXPLAIN ANALYZE` output shows `Seq Scan` on `pbp` or `player_stats` tables.
- Query latency exceeds 500ms on filtered single-season queries.
- Agent node logs show DB query time dominating total node execution time.

**Phase:** Address in Phase 1 (data pipeline / schema design). Indexes must be in the schema DDL before first data load.

---

### Pitfall 8: Synthetic Parlay Correlation Assumptions — Treating Correlated Events as Independent

**What goes wrong:** The Synthetic Parlay Builder identifies "correlated events" to construct parlays, but uses the wrong definition of beneficial correlation. Positive correlation between parlay legs (both outcomes tend to happen together) increases the parlay's true probability above what independent-leg multiplication implies — but only if you correctly identify and quantify the correlation. Negative correlation destroys value. A common mistake is building same-game parlays where the correlation is assumed positive but is actually negative (e.g., the winning team's QB passing yards are negatively correlated with a high margin of victory — blowouts feature more rushing in the 4th quarter, fewer late passing attempts).

**Why it happens:** Intuition about correlation often wrong. "Same game = correlated = good" is a naive rule. The actual correlation depends on game script, which is itself uncertain.

**Consequences:** Parlays priced as +EV are actually -EV. The builder generates recommendations that look mathematically sound but exploit a spurious or sign-inverted correlation.

**Prevention:**
- Compute historical correlation coefficients from PostgreSQL before any parlay recommendation. Never assume correlation direction — measure it.
- Require a minimum sample size (N > 200 historical occurrences of both outcomes) before any correlation-based parlay is flagged as +EV.
- Build a correlation sign test into the parlay builder: if correlation between legs is negative, the true parlay probability is below independent multiplication — flag as worse than standard parlay, not better.
- Document the specific prop pairs that are empirically positively correlated in NFL data (e.g., QB passing yards and WR1 receiving yards in pass-heavy teams) and restrict the builder to known-good pairs initially.

**Detection:**
- Parlay builder recommends same-game parlays involving running back rushing yards and wide receiver receiving yards in the same game (negative correlation in game script).
- Recommended parlay EV appears implausibly high (>20% edge) — likely a sign-inverted correlation calculation.
- Historical backtest of recommended parlays shows negative ROI despite positive calculated EV.

**Phase:** Address in Phase 3 (Synthetic Parlay Builder). Do not build the parlay engine until the correlation measurement infrastructure (Phase 2) is in place.

---

## Moderate Pitfalls

---

### Pitfall 9: LangGraph Graph Definition vs. Runtime State Confusion

**What goes wrong:** Developers conflate graph-level configuration (compiled graph structure, node definitions, edge routing) with runtime state (the `TypedDict` that flows through nodes). Attempting to modify graph structure at runtime (e.g., dynamically adding nodes based on analysis results) causes cryptic errors or silently creates a new graph that discards in-progress state. LangGraph graphs are compiled — they are immutable after `graph.compile()`.

**Prevention:**
- Design the graph structure to be fully static and compiled once at startup. Dynamic behavior lives in node logic (conditional edges, tool selection), not in graph topology.
- Use `Command` objects or conditional edge functions for routing decisions rather than attempting runtime graph modification.
- Keep graph definition code in a separate module from agent node code. Never import mutable state into the graph definition module.

**Phase:** Phase 1 (graph architecture).

---

### Pitfall 10: Fractional Kelly Over-Sizing on Small Sample Win Rates

**What goes wrong:** Kelly Criterion requires an accurate edge estimate (`p` = true win probability). With fewer than 30-50 historical comparable situations, the edge estimate has wide confidence intervals. Even "fractional" Kelly (e.g., quarter-Kelly) applied to an edge estimated from 10 samples is effectively full Kelly on a noisy signal — the fraction does not compensate for estimation error.

**Prevention:**
- Require a minimum sample size threshold before any Kelly sizing is emitted. Below N=50 comparable historical situations, output `NO_BET: insufficient sample` rather than a Kelly fraction.
- Apply an additional shrinkage factor proportional to `1/sqrt(N)` on top of the fractional Kelly multiplier for low-sample situations.
- Log the sample size alongside every Kelly recommendation so the user can judge confidence.

**Phase:** Phase 2 (Quant Agent + Kelly sizing).

---

### Pitfall 11: Playwright/BeautifulSoup Scrapers Without Anti-Bot Mitigation

**What goes wrong:** Scrapers for injury reports, weather, and social signals get blocked after repeated requests from the same IP. Production pipelines that depend on scraped data fail silently — the scraper returns an empty result instead of raising an error when blocked (HTTP 200 with a CAPTCHA or login page HTML instead of data).

**Prevention:**
- Validate scraper output shape (expected HTML structure, minimum content length) before treating a response as successful. A 200 response with <500 bytes is almost certainly a block page.
- Add configurable retry-with-backoff and rotate User-Agent headers.
- Treat scraped data as opportunistic enrichment, not required input. The Quant Agent must function without scraper data — scraper outputs augment but never gate the core pipeline.

**Phase:** Phase 2 (Context Agent scraping).

---

### Pitfall 12: PostgreSQL `to_sql` Default `if_exists='replace'` Deletes Historical Data

**What goes wrong:** `df.to_sql('pbp', engine, if_exists='replace')` drops and recreates the entire table on every run. On a re-run after a partial failure, this silently deletes previously loaded data. With `if_exists='append'` (the correct choice) and no deduplication logic, re-runs create duplicate rows.

**Prevention:**
- Always use `if_exists='append'` with an explicit deduplication strategy. Use `INSERT ... ON CONFLICT DO NOTHING` via SQLAlchemy's `insert().prefix_with('OR IGNORE')` or PostgreSQL's `ON CONFLICT` clause.
- Define a natural primary key on the PBP table (`game_id`, `play_id`) and enforce it as a database constraint so the DB rejects duplicates at the insert level.

**Phase:** Phase 1 (data pipeline).

---

## Minor Pitfalls

---

### Pitfall 13: LLM Context Window Stuffing with Raw DataFrames

**What goes wrong:** An agent node converts a Pandas DataFrame to a string and includes it in the LLM prompt. Even a small DataFrame (100 rows × 20 columns) consumes thousands of tokens. At scale, this is expensive and degrades LLM reasoning quality (models lose coherence on very long prompts).

**Prevention:** Never pass raw tabular data to LLM nodes. Summarize DataFrames to statistical aggregates (mean, percentile, trend direction) before including in context. The LLM reasons about summaries; DB queries retrieve raw numbers.

**Phase:** Phase 1 (agent node design patterns).

---

### Pitfall 14: Hardcoded Season/Week Constants in Query Logic

**What goes wrong:** Query logic hardcodes `WHERE season = 2023` or uses `datetime.now().year` as the current NFL season, which is wrong from February through August (the NFL season year is the calendar year of the season start, not the Super Bowl).

**Prevention:** Implement a `current_nfl_season()` utility function that returns the correct season year based on the NFL calendar (season starts September; Super Bowl is in February of the following year). Use this everywhere, never `datetime.now().year` directly.

**Phase:** Phase 1 (data pipeline utilities).

---

### Pitfall 15: The Odds API Sport Key Naming Changes

**What goes wrong:** The Odds API uses string sport keys like `americanfootball_nfl`. These keys occasionally change or new keys are added (e.g., for playoffs vs. regular season). Hardcoding the string causes silent failures when the key changes.

**Prevention:** Fetch the `/sports` endpoint at startup and assert that the expected sport key exists before beginning any odds ingestion run. Store the valid sport keys in config, not scattered as string literals.

**Phase:** Phase 2 (odds ingestion).

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Graph state schema definition | Reducer conflicts (Pitfall 3) | Define all reducers before writing any agent node |
| Data ingestion architecture | nfl_data_py OOM (Pitfall 4) | Year-by-year loop, column whitelist, gc.collect() |
| Pydantic model design | v2 validator bypass (Pitfall 5) | Pin v2, use native decorators, `strict=True` |
| Schema DDL creation | Missing indexes (Pitfall 7) | Add composite indexes before first data load |
| DB write strategy | `to_sql` replace bug (Pitfall 12) | `if_exists='append'` + ON CONFLICT DO NOTHING |
| LLM node design | Hallucinated stats (Pitfall 1) | `data_source` annotation, write-scope enforcement |
| Kelly sizing implementation | Correlation blindness (Pitfall 2) | CorrelationGuard node before any bet output |
| Kelly sizing implementation | Small-sample over-sizing (Pitfall 10) | N >= 50 sample gate before emitting Kelly fraction |
| Odds ingestion | Rate limit exhaustion (Pitfall 6) | Budget manager + cache layer before polling loop |
| Parlay builder | Correlation sign error (Pitfall 8) | Empirical correlation coefficients, N>200 gate |
| Context Agent scrapers | Silent block detection (Pitfall 11) | Response shape validation, treat as optional input |
| Any agent node | DataFrame-in-prompt (Pitfall 13) | Summarize to aggregates; never pass raw tables to LLM |

---

## Sources

- Training knowledge (cutoff August 2025): LangGraph v0.2.x state management, Pydantic v2 migration semantics, Kelly Criterion mathematical properties, nfl_data_py dataset characteristics, The Odds API v4 rate limiting structure. **Confidence: MEDIUM** — core mathematical and architectural claims are HIGH confidence; specific API surface details (e.g., exact header names, current rate limits) should be verified against live documentation before implementation.
- External research tools were unavailable in this session. All findings should be cross-referenced with official LangGraph, Pydantic v2, and The Odds API documentation before implementation.
