# Feature Landscape

**Domain:** Quantitative +EV sports betting analytics (NFL-first, multi-agent)
**Researched:** 2026-03-09
**Confidence note:** Web search unavailable; findings drawn from training knowledge of The Odds API, nfl_data_py, LangGraph, professional quant betting platforms (Pinnacle, Bet Labs, Pikkit, SharpSide, OddsJam, Action Network Pro), and algorithmic trading discipline. Marked MEDIUM confidence throughout; recommend verifying competitor feature sets when web access is available.

---

## Table Stakes

Features users (quantitative bettors) expect from any serious platform. Missing = product feels amateurish or unusable.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Live odds ingestion from multiple books | Without real-time lines, EV math is stale | Medium | The Odds API covers 40+ books; polling interval matters — sub-60s for pre-game, sub-5s for live |
| Opening line vs. closing line (CLV) tracking | CLV is the primary signal that a bettor is beating the market; no serious quant ignores it | Medium | Requires storing historical line snapshots — not just current lines |
| Implied probability calculation (vig removal) | Raw odds include bookmaker margin; raw percentages are meaningless for EV | Low | Multiple methods: Pinnacle sharp method, multiplicative, additive — must pick one and document it |
| +EV flag with edge percentage displayed | Core output: "this bet has +4.2% edge" — without it there's no actionable signal | Low | Depends on accurate probability model; EV = (p * win_payout) - (1-p) |
| Kelly Criterion bet sizing | Required by anyone using proper bankroll management; flat bets are quant malpractice | Low-Med | Fractional Kelly (0.25x–0.5x) is standard; full Kelly is too aggressive for real variance |
| Historical NFL box score data | Baseline for any predictive model; minimum 5–10 seasons | Low | nfl_data_py covers this well; index on game_id, team, season, week |
| Injury/availability signal integration | Player availability is the #1 external variable for NFL lines; ignoring it = bad model | Medium | Structured data from official injury reports; not free-text parsing |
| Data integrity / no LLM hallucination guardrails | Any quant platform that lets an LLM invent stats is a liability not an asset | Medium | Pydantic validation layer on all model outputs before DB queries |
| Backtesting framework | Can't validate an edge without historical simulation; users won't trust an untested model | High | Requires clean historical odds + outcomes aligned with game data |
| Win/loss tracking with ROI reporting | Users need to know if recommendations actually made money over time | Low-Med | Standard analytics: units won/lost, ROI %, CLV captured |

---

## Differentiators

Features that set this platform apart from existing tools. Not expected, but create strong competitive moat.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Multi-agent LangGraph orchestration with explicit routing | Most tools are monolithic pipelines; agent-based routing enables parallel specialization (context, quant, kinematic, arb) | High | The routing graph itself is a differentiator — agents can be upgraded independently |
| Kinematic agent (Next Gen Stats tracking data) | No mainstream +EV tool uses NGS separation, time-to-throw, press-man coverage rates as geometric matchup signals; this is the alpha layer | High | Requires NGS data access (nfl_data_py has partial coverage); matchup geometry (slot WR vs press man CB) is underused by market |
| Synthetic parlay builder with correlation analysis | Most parlay tools are purely combinatorial (ignorant of correlations); mathematically sound correlated parlay identification is rare | High | Requires covariance matrix across game events; hard stop on anti-correlated legs |
| Context agent qualitative signal integration | Weather (wind speed affects passing game), stadium surface, travel distance, divisional familiarity — bundled into a quantified game-state JSON | Medium-High | The alpha is systematizing what sharp bettors do manually; structured output feeding the quant model |
| Correlation hard-stops (anti-conflicting exposure) | Prevents the user from backing both the over AND a QB rushing prop in the same game — a real risk management gap in consumer tools | Medium | Similar to prop firm daily drawdown logic applied to bet portfolio construction |
| Dynamic SQL query generation via Pydantic-validated LLM | Natural language query interface over historical data without hallucination risk — a genuine DX differentiator for quant analysts | High | Strict schema validation must catch type errors, out-of-range values, undefined columns before execution |
| Game-state JSON as shared agent memory | A single source of truth updated continuously by the Context Agent and read by all other agents; prevents stale data in reasoning chains | Medium | LangGraph state graph handles this natively; design the schema carefully — it's hard to refactor later |
| Modular agent graph (agents replaceable without pipeline rewrite) | Each agent is a node; swap Quant Agent's model without touching Arbitrage or Kinematic agents | Medium | LangGraph node contracts enforced by Pydantic input/output schemas |
| Professional quant terminal UX (dark mode, high-density, widget-based) | Consumer sportsbook UIs are noise; a Bloomberg-style terminal for sports is a niche but strong positioning signal | High (deferred to post-v1) | Not a v1 concern — backend-first. But the UX philosophy should inform data output structures now |

---

## Anti-Features

Features to explicitly NOT build — they waste time, dilute focus, or actively harm the product.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| LLM as a data source | LLMs hallucinate statistics. A model that invents a player's yards per carry is worse than no model | Pydantic-validated DB and dataframe queries only; LLM is orchestration logic exclusively |
| Flat bet recommendations | Flat bets ignore bankroll volatility and expected value; any serious quant user will reject this immediately | Fractional Kelly sizing only; always output a unit fraction, never "bet $100" |
| Parlay construction without correlation analysis | Naive parlays multiply individual probabilities assuming independence; most parlay legs are correlated (same game) | Implement covariance analysis before any multi-leg output; block anti-correlated combinations |
| Real-time streaming frontend in v1 | Premature frontend investment before backend math is validated is a classic startup mistake | Validate math, data pipeline, and agent graph first; frontend is deferred out of scope |
| NBA pipeline in v1 | Spreading data pipeline work across two sports dilutes NFL model quality and delays validation | NFL-only until pipeline is proven; NBA is v2 |
| OAuth / multi-user in v1 | Adds auth complexity before the core product has any users | Single-user local setup; add auth when there's a reason to |
| Consumer sportsbook UI patterns | Color-coded "BET NOW" buttons, promotional odds, parlay insurance widgets — these signal a toy, not a tool | Dark mode, high-density terminal paradigm; quant finance aesthetics, not DraftKings |
| Free-text injury parsing from Twitter/Reddit | Unstructured social signal parsing is a reliability nightmare; signal-to-noise is poor for structured inference | Use official injury reports (structured), not social scraping; social sentiment is a v3 problem at earliest |
| Full Kelly sizing | Full Kelly maximizes log utility but produces bankroll variance that most users cannot tolerate psychologically or practically | Fractional Kelly (0.25x standard; 0.5x aggressive cap) always |
| Scraping sportsbook odds directly | TOS violations, brittle DOM dependencies, IP bans — not worth it when The Odds API exists | Use The Odds API exclusively for odds data |
| O(N²) table scans on historical data | Multi-year NFL datasets become slow fast without indexing; unindexed queries will make the platform feel broken | Proper composite indexes on (season, week, team, game_id) from day one |

---

## Feature Dependencies

```
[Odds Ingestion: The Odds API] ──────────────────────────────────┐
                                                                  ▼
[NFL DB: nfl_data_py + PostgreSQL] ──► [Quant Agent: Probability Model] ──► [+EV Flag]
                                                    │                              │
[Context Agent: Injuries/Weather/Surface] ──────────┘                             │
                                                                                   ▼
[Kinematic Agent: NGS Tracking Data] ──────────────────────────────► [Kelly Sizing Output]
                                                                                   │
[Arbitrage Agent: Live Odds vs Model] ──────────────────────────────► [Bet Recommendation]
                                                                                   │
[Correlation Hard-Stop Logic] ──────────────────────────────────────► [Portfolio Guard]
                                                                                   │
[Synthetic Parlay Builder] ─────────────────────────► [Validated Multi-Leg Output]
                                │
          requires: Covariance analysis on game event outcomes
          requires: Correlation hard-stop logic (shared component)
```

**Hard dependency chain:**
1. PostgreSQL schema + nfl_data_py ingest must exist before any agent can query data
2. Probability model must exist before EV calculation is possible
3. EV calculation must exist before Kelly sizing is meaningful
4. Kelly sizing must exist before any bet recommendation is valid
5. Correlation analysis must exist before synthetic parlay builder is built (otherwise it produces harmful output)

**Agent dependencies:**
- Context Agent updates game-state JSON — all other agents read from it; Context Agent must run first in each graph execution
- Arbitrage Agent depends on both the Quant Agent's probability output AND live odds from The Odds API
- Kinematic Agent is additive (enhances the probability model) but not required for the core EV calculation to function

---

## MVP Recommendation

**Prioritize (v1 scope):**

1. PostgreSQL schema with nfl_data_py ingest + composite indexes (everything else blocks on this)
2. Pydantic validation layer on all LLM-generated SQL (data integrity is non-negotiable)
3. Context Agent: structured injury/weather/surface signals → game-state JSON
4. Quant Agent: probability model via validated DB queries + EV calculation
5. Arbitrage Agent: Odds API ingestion + implied probability calculation + +EV flagging
6. Fractional Kelly sizing output (hard constraint from PROJECT.md)
7. Correlation hard-stops (prevent conflicting market exposure in same graph run)

**Defer (post-v1):**
- Kinematic Agent (NGS tracking): High complexity, high alpha — but the base probability model must be validated before this layer adds signal cleanly
- Synthetic Parlay Builder: Requires covariance analysis infrastructure that should come after the single-bet pipeline is stable
- Frontend terminal: Backend-first by design; defer until math is validated
- Backtesting framework: Critical for trust, but not needed to validate the live pipeline architecture
- CLV tracking: Requires historical line snapshots from day one of data collection; set up the logging now but don't build the analysis UI yet

**Phases implied by dependencies:**

| Phase | Focus | Key Output |
|-------|-------|------------|
| 1 | Data foundation | PostgreSQL + nfl_data_py pipeline, Pydantic validation |
| 2 | Core agent graph | Context Agent + Quant Agent + EV calculation |
| 3 | Arbitrage + risk output | Odds ingestion + +EV flag + Kelly sizing + correlation stops |
| 4 | Alpha layer | Kinematic Agent + NGS integration |
| 5 | Portfolio features | Synthetic parlay builder + backtesting |
| 6 | Frontend terminal | High-density quant UI (deferred out of v1) |

---

## Sources

**Confidence: MEDIUM** — No web access during this research session. Findings are based on:

- Training knowledge of The Odds API documentation (v4 API, 40+ sportsbooks, sports coverage)
- nfl_data_py library capabilities (nflfastR-derived data, Next Gen Stats partial coverage)
- LangGraph architecture patterns for multi-agent state graphs
- Professional betting platforms: OddsJam, SharpSide, Action Network Pro, Pikkit, Bet Labs (Sports Insights) — feature sets known from training data
- Algorithmic trading risk management conventions (prop firm rules, Kelly Criterion literature, correlation/covariance in portfolio construction)
- PROJECT.md constraints (stack, scope, and design principles defined by the project owner)

**Validation recommended:** When web access is available, verify current OddsJam and SharpSide feature sets directly; check The Odds API v4 changelog for polling limits and market coverage; confirm nfl_data_py Next Gen Stats field availability for current season.
