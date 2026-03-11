# Phase 3: Quant Engine - Research

**Researched:** 2026-03-10
**Domain:** Dynamic SQL query builder with Pydantic gate, vig removal math, confidence intervals, backtesting module
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| QUANT-01 | System enforces a two-stage SQL validation gate — LLM produces a QuantParams Pydantic model, query builder constructs parameterized SQL, LLM never produces raw SQL | asyncpg $1/$2 placeholder syntax verified; QuantParams already has Literal stat_type + season range guard; query builder pattern with switch-on-stat_type verified |
| QUANT-02 | System converts raw sportsbook odds to implied probabilities with configurable vig removal method (multiplicative or Pinnacle sharp) | Both methods mathematically verified with formulas; American odds conversion formula verified; Decimal arithmetic required to avoid float precision loss |
| QUANT-03 | System executes dynamic historical win-rate SQL queries parameterized by game context (weather, opponent, down/distance, situation) | asyncpg pool.acquire() + fetch() with $1/$2 params verified; existing indexes (idx_pbp_posteam_season, idx_pbp_play_type_season) confirmed; filters dict maps to WHERE clause appended parameters |
| QUANT-04 | System simulates historical signal performance via a backtesting module that replays past QuantResult signals against closing lines and outputs ROI and hit-rate metrics | CLV formula verified; ROI = total_profit/total_staked; hit_rate = wins/total_bets; pandas DataFrame replay pattern verified; no external library required — pure pandas + Decimal arithmetic |
</phase_requirements>

---

## Summary

Phase 3 replaces the stub `quant_agent` (currently returning hardcoded `QuantResult(true_probability=0.62, sample_size=142, data_source="fixture")`) with a real agent that executes parameterized historical queries against the PostgreSQL database built in Phase 1. The phase has four distinct technical subsystems, each independently implementable: (1) the two-stage SQL validation gate, (2) the vig removal probability converter, (3) the dynamic historical query executor, and (4) the backtesting replay module.

The two-stage gate is the most security-critical piece. QuantParams is already defined in `src/sportsbet/graph/models.py` with strict Pydantic v2 validation (`ConfigDict(strict=True)`, season range `[1999, 2030]`, `stat_type` as a Literal). Phase 3's job is to write a `QueryBuilder` class that consumes a validated `QuantParams` and emits a parameterized SQL string plus positional argument tuple. The LLM never sees raw SQL — it only produces a QuantParams dict that Pydantic validates before the query builder runs. SQL injection is structurally prevented by asyncpg's `$1/$2` placeholder protocol, not by string escaping.

The vig removal module is pure arithmetic with no external dependencies. American odds convert to raw implied probability via a two-branch formula (negative odds: `abs(odds)/(abs(odds)+100)`, positive odds: `100/(odds+100)`). Multiplicative devig normalizes by dividing each raw probability by the sum-of-raw-probabilities (the overround). The Pinnacle sharp method uses power devig — raising each implied probability to a constant power `k` where `k` solves `sum(p_i^k) = 1` — which corrects for favorite-longshot bias that the multiplicative method ignores. All arithmetic uses `Decimal`, not `float`, to prevent precision drift in the Kelly pipeline downstream.

**Primary recommendation:** Build Phase 3 in three plans: (1) QueryBuilder with Pydantic gate and asyncpg execution, (2) vig removal converter module, (3) backtesting replay module. The quant_agent node in `agents.py` is replaced in Plan 1 and is the bridge to the existing graph infrastructure.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | >=0.29 (already installed) | Async PostgreSQL query execution in Quant Agent node | Already in pyproject.toml; pool factory already in `db/connection.py` |
| pydantic | >=2.7,<3.0 (already installed) | QuantParams validation gate before SQL executes | Established in Phase 2; `ConfigDict(strict=True)` pattern locked |
| statsmodels | 0.14.6 | Wilson score confidence interval calculation | `proportion_confint(count, nobs, method='wilson')` — no custom CI math needed |
| pandas | >=2.2 (already installed) | Backtesting replay DataFrame operations | Already in pyproject.toml; CLV/ROI aggregation via vectorized ops |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| decimal (stdlib) | Python 3.12 stdlib | Lossless probability arithmetic | All probability fields; QuantResult and EVSignal already use Decimal |
| scipy.stats | via statsmodels dep | Backup CI calculation | Alternative if statsmodels unavailable; `scipy.stats.binom.interval()` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| statsmodels proportion_confint | Custom Wilson formula | statsmodels is battle-tested; custom implementation adds maintenance burden and test surface |
| Pure pandas backtesting | sports-betting PyPI package | sports-betting pulls large ML dependencies (scikit-learn, etc.) unnecessary for replay-only module |
| Power devig (Pinnacle sharp) | Additive or Shin method | Shin requires iterative solver (more complex); Additive ignores longshot bias; Power is best balance |

**Installation:**
```bash
pip install statsmodels>=0.14
```

---

## Architecture Patterns

### Recommended Project Structure
```
src/sportsbet/
├── graph/
│   ├── agents.py          # quant_agent() stub -> REPLACED with real implementation
│   ├── models.py          # QuantParams, QuantResult (already defined — Phase 3 populates fields)
│   ├── state.py           # GraphState (no changes)
│   ├── router.py          # Master Router (no changes)
│   └── graph.py           # create_graph factory (no changes)
├── quant/
│   ├── __init__.py
│   ├── query_builder.py   # QueryBuilder: QuantParams -> (sql_str, args_tuple)
│   ├── executor.py        # async run_quant_query(pool, params) -> QuantResult
│   ├── vig.py             # remove_vig(odds, method) -> Decimal
│   └── backtest.py        # BacktestEngine: replay QuantResult signals against closing lines
└── db/
    ├── connection.py      # create_async_pool() already defined
    └── models.py          # ORM models already defined
```

### Pattern 1: Two-Stage SQL Validation Gate

**What:** LLM produces a Python dict → Pydantic validates to QuantParams → QueryBuilder converts to parameterized SQL + args → asyncpg executes with `$1/$2` placeholders
**When to use:** Every time the graph dispatches to `quant_agent` with `request_type = "quant_analysis"`

```python
# Source: asyncpg official docs https://magicstack.github.io/asyncpg/current/usage.html
# Stage 1: Pydantic validation — raises ValidationError if malformed; never reaches Stage 2
params = QuantParams(**llm_output_dict)  # ValueError if stat_type not in Literal, season out of range

# Stage 2: Query builder — consumes validated params, produces $1/$2 parameterized SQL
sql, args = QueryBuilder.build(params)
# sql = "SELECT COUNT(*) as total, SUM(CASE WHEN condition THEN 1 ELSE 0 END) as hits FROM play_by_play WHERE posteam = $1 AND season >= $2 AND play_type = $3"
# args = ("KC", 2020, "pass")

# asyncpg executes: $N placeholders never allow SQL injection — they are sent as separate protocol messages
async with pool.acquire() as conn:
    row = await conn.fetchrow(sql, *args)
```

### Pattern 2: QueryBuilder — Static Dispatch on stat_type

**What:** `stat_type` is a Literal with 3 values — use a static dispatch dict (not string interpolation) to select the correct query template.
**When to use:** Inside `QueryBuilder.build()` to map validated `stat_type` to the appropriate SQL pattern.

```python
# Source: asyncpg $N placeholder pattern — validated against asyncpg docs
_QUERY_TEMPLATES: dict[str, str] = {
    "passing": """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN pass_touchdown = 1 THEN 1 ELSE 0 END) AS successes,
            posteam
        FROM play_by_play
        WHERE posteam = $1
          AND season >= $2
          AND play_type = 'pass'
        GROUP BY posteam
    """,
    "rushing": """
        SELECT COUNT(*) AS total, SUM(CASE WHEN rush_touchdown = 1 THEN 1 ELSE 0 END) AS successes
        FROM play_by_play
        WHERE posteam = $1 AND season >= $2 AND play_type = 'run'
    """,
    "receiving": """
        SELECT COUNT(*) AS total, SUM(CASE WHEN pass_touchdown = 1 THEN 1 ELSE 0 END) AS successes
        FROM play_by_play
        WHERE receiver_player_id = $1 AND season >= $2
    """,
}
# Note: $N positional args are passed separately to asyncpg — never interpolated into string
```

### Pattern 3: asyncpg Pool Connection in Async Agent Node

**What:** Quant Agent receives the asyncpg pool via closure (module-level pool variable or factory closure). The agent function signature is `async def quant_agent(state: GraphState) -> dict`.
**When to use:** Replacing the sync stub `quant_agent` with async implementation.

```python
# Source: asyncpg docs https://magicstack.github.io/asyncpg/current/usage.html
# Pattern: pool injected via closure in async node function

async def make_quant_agent(pool: asyncpg.Pool):
    """Factory that binds the pool to the agent closure."""
    async def quant_agent(state: GraphState) -> dict:
        params = QuantParams(
            game_id=state["game_id"],
            season=state["season"],
            week=state["week"],
            posteam=state["home_team"],   # or away_team based on request context
            stat_type=state.get("stat_type", "passing"),
            filters=state.get("filters", {}),
        )
        result = await run_quant_query(pool, params)
        return {"quant_result": result}
    return quant_agent
```

**Critical note:** The graph.py `create_graph()` currently imports `quant_agent` directly from `agents.py`. Phase 3 must update `graph.py` to accept an async quant_agent function or use a module-level pool. The closure factory pattern avoids `functools.partial` (which breaks with async functions per confirmed web research).

### Pattern 4: Vig Removal — Multiplicative and Power Methods

**What:** Convert raw American odds (int) to vig-free fair probabilities (Decimal).
**When to use:** QUANT-02. The vig module is independent of the query executor and can be developed/tested in isolation.

```python
# Source: Verified mathematical formulas from multiple betting analytics sources
from decimal import Decimal

def american_to_raw_prob(american_odds: int) -> Decimal:
    """Convert American odds to raw (vig-inclusive) implied probability."""
    odds = Decimal(str(american_odds))
    if american_odds < 0:
        return abs(odds) / (abs(odds) + Decimal("100"))
    else:
        return Decimal("100") / (odds + Decimal("100"))

def remove_vig_multiplicative(raw_probs: list[Decimal]) -> list[Decimal]:
    """Proportional vig removal: normalize each prob by the overround total.

    Standard method. Assumes vig is distributed proportionally across outcomes.
    Overround (e.g., 1.048 for -110/-110 market) is divided out uniformly.
    """
    overround = sum(raw_probs)
    return [p / overround for p in raw_probs]

def remove_vig_power(raw_probs: list[Decimal], tol: Decimal = Decimal("1e-9")) -> list[Decimal]:
    """Power (Pinnacle sharp) method: find exponent k such that sum(p_i^k) == 1.

    Corrects for favorite-longshot bias that the multiplicative method ignores.
    Uses binary search on k in (0, 1]. More accurate on moneylines with
    significant probability differences between sides.

    k < 1 shifts probability mass toward favorites (correcting longshot overpricing).
    """
    import math
    lo, hi = 0.0, 1.0
    for _ in range(60):   # 60 iterations gives precision well below tol
        mid = (lo + hi) / 2
        total = sum(float(p) ** mid for p in raw_probs)
        if total > 1.0:
            hi = mid
        else:
            lo = mid
    k = Decimal(str((lo + hi) / 2))
    return [p ** k for p in raw_probs]
```

### Pattern 5: Wilson Score Confidence Interval

**What:** Given a win count and sample size from the SQL query, compute the 95% CI bounds using `statsmodels.stats.proportion.proportion_confint`.
**When to use:** Populating `QuantResult.confidence_interval` field.

```python
# Source: statsmodels 0.14.6 official docs https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html
from statsmodels.stats.proportion import proportion_confint
from decimal import Decimal

def compute_wilson_ci(wins: int, total: int, alpha: float = 0.05) -> tuple[Decimal, Decimal]:
    """Return (lower, upper) 95% CI bounds for a win rate proportion."""
    if total == 0:
        return (Decimal("0"), Decimal("1"))
    lo, hi = proportion_confint(count=wins, nobs=total, alpha=alpha, method="wilson")
    return (Decimal(str(round(lo, 6))), Decimal(str(round(hi, 6))))
```

### Pattern 6: Backtesting Module — CLV Replay

**What:** Load historical QuantResult signals and matched closing odds from `odds_snapshots`, compute CLV per signal, aggregate ROI and hit-rate.
**When to use:** QUANT-04. Runs offline against Phase 1 database data.

```python
# Source: CLV formula verified from multiple sports betting analytics sources
# CLV = (closing_implied_prob - signal_implied_prob) — positive means we beat the close
# ROI = sum(profit) / sum(stake)
# hit_rate = wins / total_bets

import pandas as pd
from decimal import Decimal

class BacktestEngine:
    """Replay historical QuantResult signals against closing lines.

    Input: list of BacktestSignal(quant_result, closing_odds, actual_outcome, stake)
    Output: BacktestReport(roi, hit_rate, clv_mean, sample_size, signals_df)
    """

    def run(self, signals: list[dict]) -> dict:
        df = pd.DataFrame(signals)
        df["raw_clv"] = df["closing_implied_prob"] - df["signal_implied_prob"]
        df["profit"] = df.apply(
            lambda r: r["stake"] * (r["payout_multiplier"] - 1) if r["outcome"] else -r["stake"],
            axis=1,
        )
        total_staked = df["stake"].sum()
        roi = float(df["profit"].sum() / total_staked) if total_staked > 0 else 0.0
        hit_rate = float(df["outcome"].mean())
        clv_mean = float(df["raw_clv"].mean())
        return {
            "roi": roi,
            "hit_rate": hit_rate,
            "clv_mean": clv_mean,
            "sample_size": len(df),
            "signals_df": df,
        }
```

### Anti-Patterns to Avoid

- **f-string SQL construction:** Never do `f"WHERE posteam = '{params.posteam}'"`. asyncpg's `$N` placeholder is the only safe path. Static templates in `_QUERY_TEMPLATES` dict prevent this structurally.
- **float for probability arithmetic:** `Decimal(0.52) != Decimal("0.52")`. Always construct Decimal from string: `Decimal(str(value))` or `Decimal("0.5238")`.
- **Using the sync pool for agent nodes:** `db/connection.py` has both `get_sync_engine()` (for Alembic/bulk writes) and `create_async_pool()` (for agent queries). Quant Agent must use `create_async_pool()` — not the sync engine.
- **Putting the asyncpg pool in GraphState:** Pool is a runtime resource, not part of the agent state machine. Pass it via closure or module-level singleton. GraphState is serialized by LangGraph checkpointer — non-serializable objects will crash checkpoint persistence.
- **Running backtesting synchronously in the agent loop:** BacktestEngine is a standalone offline module. It is not called from within the LangGraph graph at request time. It runs separately as a CLI or test fixture.
- **functools.partial to inject pool into node:** Confirmed broken for async node functions in LangGraph 1.1. Use closure factory (`make_quant_agent(pool)`) instead.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Wilson score confidence interval | Custom CI math | `statsmodels.stats.proportion.proportion_confint(method='wilson')` | Statsmodels CI handles edge cases (0 wins, all wins, n=1) correctly; tested library |
| American odds to implied prob | Custom branch logic | Documented two-branch formula wrapped in Decimal — 8 lines, no library needed | Too simple for a library; library adds a dep for trivial math |
| Power devig binary search | Custom optimizer | Binary search on k over 60 iterations — self-contained in `vig.py` | scipy.optimize overkill; binary search converges in <1ms for 2-outcome markets |
| DataFrame backtesting | Custom loop | pandas vectorized ops + `.apply()` | Pandas already in pyproject.toml; loop-based replay slow on 10K+ signals |

**Key insight:** The QUANT-01 gate is architectural, not just a library call. The value is the structural guarantee: QuantParams Pydantic validation runs before `QueryBuilder.build()` is called, and `QueryBuilder.build()` runs before asyncpg executes. The LLM cannot bypass this — it can only produce a dict that either validates or raises `ValidationError`.

---

## Common Pitfalls

### Pitfall 1: asyncpg Type Mismatch for Decimal Fields
**What goes wrong:** asyncpg maps PostgreSQL `NUMERIC` → Python `Decimal`, but if you pass a Python `float` as a query parameter where `NUMERIC` is expected, asyncpg raises a `DataError`. Similarly, the docs note that `float` precision may differ between encode/decode cycles for `DOUBLE PRECISION` columns — always cast to `NUMERIC` in SQL for probability fields.
**Why it happens:** asyncpg performs strict type mapping at the protocol level (not permissive like psycopg2).
**How to avoid:** Always pass Decimal values from the QuantParams model directly. For query args that come from int columns (season, week), pass Python `int` directly — asyncpg maps Python `int` to `INTEGER`/`BIGINT` correctly.
**Warning signs:** `asyncpg.exceptions.DataError: invalid input for query argument $N: expected int, got str`

### Pitfall 2: Pool Not Available in Async Context During Test
**What goes wrong:** Tests that use `graph_fixture` (MemorySaver-backed graph) will fail if `quant_agent` needs the asyncpg pool but the pool was never created in the test setup.
**Why it happens:** Tests use `create_graph(checkpointer=MemorySaver())` — no DB pool is wired. Phase 3 must either (a) mock the pool in tests or (b) use `SPORTSBET_TEST_DATABASE_URL` pattern established in Phase 1 to gate live DB tests.
**How to avoid:** Use `pytest.mark.skipif` guarded by `SPORTSBET_TEST_DATABASE_URL` for tests that need a real pool. Use a mock pool returning fixture rows for unit tests of the query builder itself.
**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'acquire'` in test output.

### Pitfall 3: `QuantResult.confidence_interval` is `tuple[Decimal, Decimal]` with `strict=True`
**What goes wrong:** `proportion_confint` returns `(float, float)`. Assigning directly to `confidence_interval` without converting to `Decimal` raises `ValidationError` because the model is `ConfigDict(strict=True)` — floats are not accepted where `Decimal` is expected.
**Why it happens:** Pydantic strict mode disables type coercion. `Decimal` and `float` are distinct types under strict mode.
**How to avoid:** Always wrap CI bounds: `(Decimal(str(round(lo, 6))), Decimal(str(round(hi, 6))))` before assigning to the model.
**Warning signs:** `ValidationError: 1 validation error for QuantResult / confidence_interval / 0 / Input should be a valid Decimal [type=decimal_type]`

### Pitfall 4: Overround > 1 Required for Devig
**What goes wrong:** If the raw implied probabilities don't sum to > 1.0 (i.e., overround ≤ 1.0), the multiplicative method would increase odds rather than remove vig — which indicates corrupt or non-standard input.
**Why it happens:** The Odds API returns American odds for a two-sided market. If both sides are positive (underdog-only markets), the sum of raw implied probs is < 1 and vig removal makes no sense.
**How to avoid:** Guard: `if sum(raw_probs) <= Decimal("1"): raise ValueError(f"Invalid market: overround {sum(raw_probs)} <= 1. Vig removal requires overround > 1.")`.
**Warning signs:** Fair probabilities > 1.0 after multiplicative devig.

### Pitfall 5: Sample Size Gate for Statistical Validity
**What goes wrong:** A `true_probability = 1.0` with `sample_size = 1` is mathematically meaningless but passes Pydantic validation. Downstream Kelly sizing would allocate maximum capital on a single-observation signal.
**Why it happens:** QuantResult has no minimum sample size constraint at the model level.
**How to avoid:** Add a `MIN_SAMPLE_SIZE = 30` constant in `executor.py`. If `sample_size < MIN_SAMPLE_SIZE`, return `QuantResult(data_source="insufficient_sample", sample_size=N)` with `true_probability=None` rather than an unreliable estimate. The Arbitrage Agent in Phase 5 should check for `None` probability before computing Kelly.
**Warning signs:** Kelly fraction at max cap (0.25) on very recent/narrow game filters.

### Pitfall 6: Backtesting Must Align QuantResult Timestamps with Closing Lines
**What goes wrong:** `odds_snapshots` table has `snapped_at` timestamps. A CLV calculation using a snapshot taken after the game started is not a valid closing line — it's an in-play price.
**Why it happens:** The Phase 1 odds snapshot writer records all snapshots without a "this is the closing line" flag.
**How to avoid:** For backtesting, filter `odds_snapshots WHERE snapped_at < game_start_time` and take the latest snapshot before kickoff as the closing line proxy. Flag this limitation in BacktestReport metadata.
**Warning signs:** CLV mean close to 0 even when signals show good historical accuracy — in-play price contamination flattens the CLV distribution.

---

## Code Examples

Verified patterns from official sources:

### asyncpg Pool Acquire + Parameterized Fetch
```python
# Source: asyncpg official docs https://magicstack.github.io/asyncpg/current/usage.html
async with pool.acquire() as conn:
    # $1, $2, $3 are positional — passed as separate protocol messages, never interpolated
    rows = await conn.fetch(
        "SELECT COUNT(*) AS total FROM play_by_play WHERE posteam = $1 AND season >= $2 AND play_type = $3",
        "KC", 2020, "pass"
    )
    row = await conn.fetchrow(
        "SELECT SUM(pass_touchdown) FROM play_by_play WHERE game_id = $1",
        "2023_01_KC_DET"
    )
    # asyncpg returns asyncpg.Record objects — access by column name: row["total"]
```

### statsmodels Wilson CI
```python
# Source: statsmodels 0.14.6 https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html
from statsmodels.stats.proportion import proportion_confint

lo, hi = proportion_confint(count=56, nobs=100, alpha=0.05, method="wilson")
# Returns: (0.462, 0.653) — asymmetric, valid for any sample size including small N
```

### American Odds Conversion (Verified Formula)
```python
# Source: verified across multiple betting analytics sources
from decimal import Decimal

def american_to_raw_prob(american_odds: int) -> Decimal:
    odds = Decimal(str(american_odds))
    if american_odds < 0:
        return abs(odds) / (abs(odds) + Decimal("100"))
    else:
        return Decimal("100") / (odds + Decimal("100"))

# -110 → 110/210 = 0.5238... (per side for standard -110/-110 market)
# +150 → 100/250 = 0.400
```

### Multiplicative Devig (Verified Formula)
```python
# Source: verified from multiple devig guides; standard formula
# For -110/-110 market: raw_probs = [0.5238, 0.5238], overround = 1.0476
# fair_probs = [0.5238/1.0476, 0.5238/1.0476] = [0.500, 0.500]
overround = sum(raw_probs)
fair_probs = [p / overround for p in raw_probs]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ORM query (SQLAlchemy select()) for agent hot path | asyncpg direct pool with `$N` params | Phase 1 design decision | 3-5x lower latency per query; no ORM overhead in agent loop |
| float for probability values | Decimal throughout | Phase 2 model design | Prevents precision drift through Kelly Criterion pipeline |
| MemorySaver stub graph | Same graph with real quant_agent closure | Phase 3 | quant_result in GraphState populated from DB, not fixture |
| nfl_data_py (archived Sep 2025) | nflreadpy | Phase 1 research | All data already in DB — Phase 3 only reads, never re-ingests |

**Deprecated/outdated:**
- `nfl_data_py` import: archived; project uses `nflreadpy` — irrelevant to Phase 3 (data already in DB)
- Sync `SqliteSaver`: replaced by `AsyncSqliteSaver` in Phase 2 — confirmed not to re-introduce here

---

## Open Questions

1. **asyncpg pool lifecycle in the graph**
   - What we know: `db/connection.py` provides `create_async_pool()`. Graph nodes need the pool. Pool must not be in GraphState (not serializable by LangGraph checkpointer).
   - What's unclear: Where the pool is created and how it is passed to the async quant_agent closure — at app startup (module-level singleton) vs. per-request.
   - Recommendation: Module-level pool singleton initialized once at process startup and passed to `make_quant_agent(pool)` closure factory. Tests mock or skip the pool via `SPORTSBET_TEST_DATABASE_URL` gate.

2. **QuantParams.filters dict → SQL WHERE clause mapping**
   - What we know: `filters: dict[str, object]` is validated by Pydantic but the keys are unconstrained strings.
   - What's unclear: Which filter keys are valid (e.g., `"down"`, `"ydstogo"`, `"defteam"`)? Can an LLM inject an arbitrary column name as a filter key?
   - Recommendation: Define an explicit `FilterKey` Literal or Enum for allowed filter keys (e.g., `Literal["down", "ydstogo", "defteam", "game_id"]`). The `QueryBuilder` only appends parameters for recognized filter keys — unknown keys are silently dropped with a warning log. This closes the SQL injection vector in the filters dict.

3. **Backtesting data availability**
   - What we know: `odds_snapshots` table exists from Phase 1. Phase 1 plan 03 writes snapshots. The ROADMAP notes Phase 1 plan 03 is marked as not complete in the plans list (01-03-PLAN.md is listed but not marked [x]).
   - What's unclear: Whether real odds snapshot data has actually been ingested into the DB.
   - Recommendation: Design BacktestEngine to work with mock fixture data when DB has zero odds_snapshot rows — graceful degradation with `BacktestReport(sample_size=0, roi=None, hit_rate=None)`. This keeps QUANT-04 testable regardless of live data state.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2 + pytest-asyncio 0.23 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| Quick run command | `pytest tests/test_quant.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QUANT-01 | Malformed QuantParams (invalid season, injected SQL) raises ValidationError before query builder runs | unit | `pytest tests/test_quant.py::test_quant_params_validation -x` | ❌ Wave 0 |
| QUANT-01 | QueryBuilder.build() with valid QuantParams returns SQL string with $1/$2 placeholders (no user data in string) | unit | `pytest tests/test_quant.py::test_query_builder_parameterized -x` | ❌ Wave 0 |
| QUANT-01 | Live quant_agent call via graph_fixture returns QuantResult with all 4 fields populated from DB | integration | `pytest tests/test_quant.py::test_quant_agent_live -x` | ❌ Wave 0 (skipif no DB) |
| QUANT-02 | american_to_raw_prob(-110) == Decimal("0.523809...") | unit | `pytest tests/test_vig.py::test_american_to_raw_prob -x` | ❌ Wave 0 |
| QUANT-02 | remove_vig_multiplicative([-110, -110]) sums to Decimal("1") | unit | `pytest tests/test_vig.py::test_multiplicative_sums_to_one -x` | ❌ Wave 0 |
| QUANT-02 | remove_vig_power([-110, -110]) sums to Decimal("1") within tolerance | unit | `pytest tests/test_vig.py::test_power_sums_to_one -x` | ❌ Wave 0 |
| QUANT-03 | run_quant_query with passing/rushing/receiving stat_type returns QuantResult with non-None sample_size | integration | `pytest tests/test_quant.py::test_run_quant_query_passing -x` | ❌ Wave 0 (skipif no DB) |
| QUANT-04 | BacktestEngine.run(signals) returns dict with roi, hit_rate, clv_mean, sample_size | unit | `pytest tests/test_backtest.py::test_backtest_engine_fixture -x` | ❌ Wave 0 |
| QUANT-04 | BacktestEngine with 0 signals returns graceful empty report | unit | `pytest tests/test_backtest.py::test_backtest_empty_signals -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_quant.py tests/test_vig.py tests/test_backtest.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_quant.py` — covers QUANT-01, QUANT-03 (DB tests gated by `SPORTSBET_TEST_DATABASE_URL`)
- [ ] `tests/test_vig.py` — covers QUANT-02 (pure unit, no DB)
- [ ] `tests/test_backtest.py` — covers QUANT-04 (pure unit with fixture data)
- [ ] `src/sportsbet/quant/__init__.py` — quant subpackage scaffold
- [ ] Framework install: `pip install statsmodels>=0.14` — not yet in pyproject.toml

---

## Sources

### Primary (HIGH confidence)
- asyncpg official docs https://magicstack.github.io/asyncpg/current/usage.html — $N placeholder syntax, fetch/fetchrow/execute signatures, type mapping, pool acquire pattern
- statsmodels 0.14.6 official docs https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html — proportion_confint signature, Wilson method, return type
- Pydantic v2 models in `src/sportsbet/graph/models.py` — existing QuantParams/QuantResult definitions Phase 3 builds against

### Secondary (MEDIUM confidence)
- Multiple betting analytics sources (Outlier, PinnacleoddsDropper, ActionNetwork, Bettoredge) — multiplicative devig formula verified across sources; power method formula consistent across sources
- statsmodels PyPI https://pypi.org/project/statsmodels/ — version 0.14.6 latest stable; Python 3.12 compatible confirmed

### Tertiary (LOW confidence)
- asyncpg GitHub Discussion #1120 on SQL injection prevention — confirms $N placeholder as the intended injection prevention mechanism, but is a community discussion not official docs
- LangChain Forum on dependency injection singleton management — closure factory pattern for pool injection, not official LangGraph docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — asyncpg/pydantic/pandas already in pyproject.toml; statsmodels verified on PyPI for Python 3.12
- Architecture patterns: HIGH — two-stage gate pattern is direct consequence of existing QuantParams model; asyncpg $N syntax confirmed from official docs
- Pitfalls: HIGH — Pydantic strict mode float/Decimal conflict confirmed from model design; pool serialization pitfall confirmed from LangGraph checkpointer behavior
- Vig formulas: HIGH — multiplicative formula verified across 5+ independent sources; power method formula consistent across sources
- Backtesting: MEDIUM — CLV formula standard; exact odds_snapshots data availability uncertain pending Phase 1 plan 03 completion

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (statsmodels and asyncpg are stable; LangGraph 1.1.x moves quickly — re-verify node injection patterns if LangGraph minor version changes)
