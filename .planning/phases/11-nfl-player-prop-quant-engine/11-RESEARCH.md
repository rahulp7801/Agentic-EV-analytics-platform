# Phase 11: NFL Player Prop Quant Engine - Research

**Researched:** 2026-03-22
**Domain:** NFL player prop statistical distributions; PropQueryBuilder two-stage SQL gate; Kinematic signal integration into PropResult; asyncpg + statsmodels patterns
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-03 | System calculates true probability for NFL player props (passing yards/TDs/completions, rushing yards/attempts/TDs, receiving yards/receptions/targets) from historical PostgreSQL distributions with sample size and confidence interval | `player_stats` table already contains all NFL prop columns (passing_yards, passing_tds, completions, attempts, rushing_yards, rushing_tds, carries, receptions, targets, receiving_yards, receiving_tds); aggregate pattern from Phase 3's `run_quant_query` applies directly |
| PROP-04 | System incorporates Kinematic Agent signals (separation, press-man coverage rate) into NFL receiving prop probability estimates where NGS data is available | `GraphState.kinematic_result: Optional[KinematicAnalysis]` already in state; KinematicAnalysis has `avg_separation`, `geometric_mismatch_flag`, `press_man_rate` (always None in v1); integration is a post-query probability adjustment step, not a SQL join |
</phase_requirements>

---

## Summary

Phase 11 builds the `PropQuantAgent` — the NFL player prop analogue to the Phase 3 `QuantAgent`. Both follow the same architectural chain: `PropParams (Pydantic gate) -> PropQueryBuilder -> asyncpg parameterized SQL -> QuantResult-style PropResult`. The groundwork is fully laid: `PropParams` and `PropResult` models exist in `graph/models.py`, the `player_stats` table (containing all NFL prop stat columns) was built in Phase 1, and the Wilson CI + MIN_SAMPLE_SIZE=30 + asyncpg $N param patterns are established in `quant/executor.py`.

The core new work is in `src/sportsbet/prop/` (a new subpackage mirroring `src/sportsbet/quant/`): a `PropQueryBuilder` that handles the NFL stat-to-column mapping, and a `run_prop_query` executor that computes per-player historical distributions from `player_stats`. The query structure is fundamentally different from Phase 3: Phase 3 queries aggregate play-level counts from `play_by_play` (total plays vs successes). Phase 11 queries player-level game stat distributions from `player_stats` — the question is "in N historical weeks, how often did [player_id] exceed [line] yards?", not "how often did [team] succeed on pass plays?". This means the SQL returns a frequency distribution over a stat column, not a binary win-rate.

PROP-04 (Kinematic integration) is a post-query probability adjustment: after `run_prop_query` returns a raw `PropResult`, the agent reads `state["kinematic_result"]` and applies a signal-driven multiplier to `true_probability`. The `geometric_mismatch_flag` and `avg_separation` from `KinematicAnalysis` are the input signals. `press_man_rate` is always `None` in v1 (documented in Phase 6 decisions). The adjustment must be bounded, additive/multiplicative-bounded, and must not produce probabilities outside [0,1].

**Primary recommendation:** Create `src/sportsbet/prop/` subpackage with `query_builder.py`, `executor.py`, and `agents.py`. Build `PropQueryBuilder` following the exact structural pattern of `quant/query_builder.py` (frozenset allowlist, static SQL templates, positional args only). Implement kinematic adjustment in the agent closure, not in the executor — keeps executor pure and testable.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncpg` | >=0.29 (installed) | Async PostgreSQL queries for `player_stats` table | Already in use; pool factory in `db/connection.py`; `$N` positional param injection prevention established |
| `pydantic` | >=2.7,<3.0 (installed) | `PropParams` gate — already in `graph/models.py` | `ConfigDict(strict=True)` pattern locked; non-negotiable per CLAUDE.md |
| `statsmodels` | >=0.14 (installed) | Wilson score CI via `proportion_confint(method="wilson")` | Used in Phase 3 executor; same function, same `Decimal(str(round(...)))` wrapping |
| `decimal` (stdlib) | Python 3.12 | All probability arithmetic; `true_probability`, CI bounds | Hard rule from Phase 3: never assign `float` to a `Decimal` Pydantic field |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `structlog` | >=24.1 (installed) | Structured logging in executor and agent | Matches all other agent/executor modules |
| `gc` (stdlib) | — | Not needed in prop engine (no batch loading) | No OOM risk in per-query executor |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Frequency distribution over `player_stats` rows | Play-by-play aggregate from `play_by_play` | `player_stats` is the correct granularity for player props — game-level stat totals per week, not play-counts |
| Wilson CI (proportion of weeks exceeding line) | Normal approximation CI | Wilson is correct for small N; normal approximation fails at N<30, exactly the insufficient-sample boundary |
| Post-query kinematic multiplier | SQL JOIN on `ngs_stats` in same query | SQL JOIN adds complexity and NGS data gaps cause silent row drops; post-query adjustment is cleaner and testable independently |

### No New Dependencies

All required libraries are already in `pyproject.toml`. No `pip install` needed.

---

## Architecture Patterns

### Recommended Project Structure

```
src/sportsbet/
├── prop/                         # NEW subpackage (mirrors quant/)
│   ├── __init__.py
│   ├── query_builder.py          # PropQueryBuilder: PropParams -> (sql, args)
│   ├── executor.py               # run_prop_query(pool, params) -> PropResult
│   └── agents.py                 # make_prop_quant_agent(pool) closure factory
tests/
├── test_prop_query_builder.py    # PropQueryBuilder unit tests (TDD)
└── test_prop_executor.py         # executor tests (mock pool + real CI math)
```

The existing `tests/test_prop_models.py` covers `PropParams`/`PropResult` and is already green. Phase 11 adds two new test files.

### Pattern 1: PropQueryBuilder — NFL Stat Column Mapping

**What:** Maps `PropParams.prop_type` (Literal) to a `player_stats` column name and constructs a frequency distribution query.
**Key difference from Phase 3 QueryBuilder:** Phase 3 aggregates play counts (`COUNT(*) total, SUM(CASE...) successes`). Phase 11 counts weeks where the stat exceeded the prop line.
**SQL pattern:**

```sql
-- Template for "passing yards over/under line"
SELECT
    COUNT(*)                                           AS total,
    SUM(CASE WHEN passing_yards >= $3 THEN 1 ELSE 0 END) AS successes
FROM player_stats
WHERE player_id = $1
  AND season    >= $2
  AND passing_yards IS NOT NULL
```

The `$3` parameter is the `PropParams.line` (a `Decimal`, passed as Python `float` or `Decimal` to asyncpg — must use `float(params.line)` since asyncpg maps `Decimal` to NUMERIC but `$N` placeholders in aggregate queries work cleanly with Python `float` for comparison with `SMALLINT` columns).

**Security invariant (identical to Phase 3):**
- Column names (`passing_yards`, `rushing_yards`, etc.) come from a static `PROP_COLUMN_MAP` dict keyed by `PropParams.prop_type` Literal values — NOT user input
- All dynamic values (`player_id`, `season`, `line`) are positional `$N` params — never interpolated

```python
# Source: internal — mirrors quant/query_builder.py pattern

PROP_COLUMN_MAP: dict[str, str] = {
    "pass_yds":    "passing_yards",
    "pass_tds":    "passing_tds",
    "rush_yds":    "rushing_yards",
    "rush_tds":    "rushing_tds",
    "rec_yds":     "receiving_yards",
    "rec_tds":     "receiving_tds",
    "receptions":  "receptions",
}

PROP_ALLOWED_FILTER_KEYS: frozenset[str] = frozenset({"season", "week", "team"})

_PROP_TEMPLATE = """
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN {col} >= $3 THEN 1 ELSE 0 END) AS successes
FROM player_stats
WHERE player_id = $1
  AND season    >= $2
  AND {col} IS NOT NULL
"""
# {col} is substituted from PROP_COLUMN_MAP[params.prop_type] — a static dict,
# not user input. This is safe string formatting (allowlist substitution).
```

Note: `{col}` is an allowlist substitution from a static Python dict — this is the same structural injection prevention used in Phase 3's filter key appending. `{col}` values are hardcoded Python strings in `PROP_COLUMN_MAP`, not derived from any user input path.

### Pattern 2: run_prop_query — Executor

**What:** Async function `run_prop_query(pool, params) -> PropResult` — structural twin of `run_quant_query`.
**Min sample gate:** `MIN_PROP_SAMPLE_SIZE = 30` (same as `MIN_SAMPLE_SIZE` in Phase 3 — rationale: Wilson CI is unreliable below N=30).
**CI:** `proportion_confint(count=successes, nobs=total, alpha=0.05, method="wilson")` from statsmodels — identical call site.
**Decimal wrapping:** `Decimal(str(round(x, 6)))` for both `true_probability` and CI bounds — mandatory to satisfy `PropResult`'s `ConfigDict(strict=True)`.
**mean_stat:** Phase 11 adds a `mean_stat` calculation (average of the stat column) via a second column in the SELECT:

```sql
SELECT
    COUNT(*)                                           AS total,
    SUM(CASE WHEN {col} >= $3 THEN 1 ELSE 0 END) AS successes,
    AVG({col})                                        AS mean_val
FROM player_stats
WHERE player_id = $1
  AND season    >= $2
  AND {col} IS NOT NULL
```

`PropResult.mean_stat` is set to `Decimal(str(round(row["mean_val"], 2)))`.

### Pattern 3: Kinematic Signal Integration

**What:** After `run_prop_query` returns a `PropResult`, the agent closure reads `state["kinematic_result"]` and adjusts `true_probability` if the prop is a receiving prop (`prop_type in {"rec_yds", "rec_tds", "receptions"}`) and `kinematic_result` is not None.
**Adjustment logic:**
- Only applies when `prop_type in {"rec_yds", "rec_tds", "receptions"}` (receiving props only)
- Reads `KinematicAnalysis.geometric_mismatch_flag` and `avg_separation`
- `press_man_rate` is always `None` — do not use it (Phase 6 decision)
- When `geometric_mismatch_flag=True` (WR has high separation >= 2.5 yds threshold), apply a positive adjustment to `true_probability` for "over" props
- Adjustment must be bounded: cap to `[0.01, 0.99]` after applying multiplier
- Adjustment magnitude: configurable constant (default `KINEMATIC_BOOST = Decimal("0.05")`) — a 5 percentage point boost when mismatch flag is True. Documented as heuristic starting point (same language as `SEPARATION_THRESHOLD` in `matchup.py`)

```python
# Post-query kinematic adjustment — inside make_prop_quant_agent closure

KINEMATIC_BOOST: Decimal = Decimal("0.05")
RECEIVING_PROPS: frozenset[str] = frozenset({"rec_yds", "rec_tds", "receptions"})

def _apply_kinematic_adjustment(
    result: PropResult,
    kinematic: KinematicAnalysis | None,
    prop_type: str,
) -> PropResult:
    if kinematic is None:
        return result
    if prop_type not in RECEIVING_PROPS:
        return result
    if result.true_probability is None:
        return result
    if not kinematic.geometric_mismatch_flag:
        return result
    # Bounded additive boost
    adjusted = result.true_probability + KINEMATIC_BOOST
    adjusted = max(Decimal("0.01"), min(Decimal("0.99"), adjusted))
    return result.model_copy(update={"true_probability": adjusted, "data_source": "postgresql+kinematic"})
```

### Pattern 4: make_prop_quant_agent Closure Factory

**What:** Mirrors `make_quant_agent(pool)` exactly. Returns an async node function compatible with LangGraph's node interface.
**Pipeline:**
1. Extract `PropParams` fields from `GraphState` (or from a dedicated `prop_params` key to be added to GraphState)
2. Validate via `PropParams(...)` — raises `ValidationError` on malformed input (returns `error` state key)
3. Call `run_prop_query(pool, params)` to get base `PropResult`
4. Read `state.get("kinematic_result")` (already in `GraphState`)
5. Call `_apply_kinematic_adjustment(result, kinematic, params.prop_type)`
6. Return `{"prop_result": result}`

**GraphState extension:** `prop_result: Optional[PropResult]` must be added to `GraphState` in `state.py`. Follow the Phase 6 pattern (add at end of class, runtime import not TYPE_CHECKING).

**Routing:** `request_type = "prop_analysis"` routes to `prop_quant_agent` node.

### Anti-Patterns to Avoid

- **Using `play_by_play` for prop distributions:** Prop true probability is game-level (did the player exceed the line this week?), not play-level. Use `player_stats`, not `play_by_play`.
- **Float arithmetic on Decimal fields:** Any `float` assigned to `PropResult.true_probability` (strict=True) raises `ValidationError`. Always `Decimal(str(round(x, 6)))`.
- **Applying kinematic adjustment to non-receiving props:** Separation data is WR/TE receiving-only. `RECEIVING_PROPS` frozenset gates the adjustment.
- **Hard-coding prop line comparison as `>=` always:** In practice "over" is `>=` and "under" is `<`. Phase 11 success criterion specifies `true_probability` as the probability of exceeding the line, so `>=` is correct for the over direction. A future phase can parameterize over/under direction.
- **asyncpg type mismatch on Decimal line:** `player_stats.passing_yards` is `SMALLINT` in the ORM. Asyncpg comparison `SMALLINT >= $3` where `$3 = Decimal("250.5")` works correctly at the PostgreSQL level (implicit cast). However, passing Python `Decimal` to asyncpg for `$3` raises `asyncpg.exceptions.UndefinedFunctionError` in some configurations. Safe approach: cast `float(params.line)` for the `$3` argument. Alternatively, cast to `int` if the line is a whole number. Use `float(params.line)` consistently.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Wilson CI math | Custom confidence interval formula | `statsmodels.stats.proportion.proportion_confint(method="wilson")` | Already installed, tested in Phase 3, handles edge cases (N=0, p=0, p=1) |
| SQL injection prevention | String escaping or sanitization | asyncpg `$N` positional params + static `PROP_COLUMN_MAP` allowlist | Structural prevention — same pattern as `quant/query_builder.py` |
| Kinematic probability adjustment | Complex Bayesian update | Bounded additive constant (`KINEMATIC_BOOST`) | v1 signal is a binary flag — complex update requires calibrated prior; start simple, document as heuristic |
| `PropParams`/`PropResult` models | New Pydantic models | Use existing `PropParams`/`PropResult` from `graph/models.py` | Already implemented and tested in Phase 10 |

---

## Common Pitfalls

### Pitfall 1: Wrong Table for Prop Distributions

**What goes wrong:** Writing `PropQueryBuilder` templates that query `play_by_play` instead of `player_stats`.
**Why it happens:** Phase 3's `QueryBuilder` uses `play_by_play`. Developers copy the pattern without recognizing the table change.
**How to avoid:** `player_stats` has one row per (player_id, season, week) with aggregated stat totals. Props are game-level — "did Mahomes throw for 250+ yards in this game?" uses `player_stats`, not individual plays.
**Warning signs:** SQL returning `total` counts in the thousands (play counts) instead of dozens (game weeks).

### Pitfall 2: Float Assigned to Strict Decimal Field

**What goes wrong:** `PropResult(true_probability=0.65)` raises `pydantic.ValidationError` because `ConfigDict(strict=True)` rejects `float` for a `Decimal` field.
**Why it happens:** `asyncpg` returns Python `float` for `AVG()` aggregate results; statsmodels returns `float` for CI bounds.
**How to avoid:** Always wrap: `Decimal(str(round(x, 6)))`. Confirmed pattern from Phase 3 decisions: `Decimal(str(round(x,6))) wrapping for Wilson CI bounds`.

### Pitfall 3: asyncpg Type Error on Decimal Line Parameter

**What goes wrong:** `await conn.fetchrow(sql, player_id, season, params.line)` raises `asyncpg.exceptions._base.InterfaceError` or a PostgreSQL type error when `params.line` is a Python `Decimal` and the column is `SMALLINT`.
**Why it happens:** asyncpg maps Python `Decimal` to PostgreSQL `NUMERIC`, but comparing `NUMERIC` to `SMALLINT` in a `>=` WHERE clause can cause operator ambiguity in some PostgreSQL versions.
**How to avoid:** Pass `float(params.line)` for the line argument. PostgreSQL casts `DOUBLE PRECISION` to `SMALLINT` comparison cleanly.

### Pitfall 4: Kinematic Adjustment Produces Probability Outside [0, 1]

**What goes wrong:** `true_probability = Decimal("0.97") + KINEMATIC_BOOST` produces `Decimal("1.02")`, which is mathematically invalid and will cause downstream Kelly Criterion errors.
**Why it happens:** No bounds check after applying the boost.
**How to avoid:** Always clamp: `max(Decimal("0.01"), min(Decimal("0.99"), adjusted))` — documented in Pattern 3 above.

### Pitfall 5: GraphState Missing prop_result Field

**What goes wrong:** The LangGraph node returns `{"prop_result": result}` but `GraphState` TypedDict doesn't have a `prop_result` field, causing a runtime `KeyError` or silent state update loss.
**Why it happens:** Phase 10 defined `PropResult` but did not extend `GraphState` (that is Phase 11's job).
**How to avoid:** Add `prop_result: Optional[PropResult]` to `GraphState` in `state.py`. Follow the exact Phase 6 pattern: import `PropResult` at runtime (not under `TYPE_CHECKING`) because LangGraph calls `get_type_hints(GraphState)` which cannot resolve forward refs.

### Pitfall 6: Applying Kinematic Boost to Pass/Rush Props

**What goes wrong:** `avg_separation` and `geometric_mismatch_flag` are computed for the WR (receiver). Applying the boost to a passing yards prop for the QB is semantically wrong — separation of the receiver does not directly predict QB passing yards.
**Why it happens:** Not gating the kinematic adjustment by `prop_type`.
**How to avoid:** `RECEIVING_PROPS = frozenset({"rec_yds", "rec_tds", "receptions"})` gate — only apply adjustment when `prop_type in RECEIVING_PROPS`.

### Pitfall 7: player_id Type Mismatch

**What goes wrong:** `player_stats.player_id` is `VARCHAR(20)` (string GSIS ID like `"00-0033873"`). `PropParams.player_id` is `str`. But asyncpg requires the argument type to match. This is safe — both are `str`. However, NBA `player_id` is an integer in `nba_player_stats`. Don't confuse the two tables.
**How to avoid:** Phase 11 only touches `player_stats` (NFL). The `player_id` in PropParams is `str` and `player_stats.player_id` is `VARCHAR(20)` — consistent.

---

## Code Examples

### PropQueryBuilder — Core Build Method

```python
# src/sportsbet/prop/query_builder.py (to be created)
# Source: extends quant/query_builder.py pattern; verified against db/models.py player_stats schema

PROP_COLUMN_MAP: dict[str, str] = {
    "pass_yds":   "passing_yards",
    "pass_tds":   "passing_tds",
    "rush_yds":   "rushing_yards",
    "rush_tds":   "rushing_tds",
    "rec_yds":    "receiving_yards",
    "rec_tds":    "receiving_tds",
    "receptions": "receptions",
}

PROP_ALLOWED_FILTER_KEYS: frozenset[str] = frozenset({"week", "team"})

_NFL_PROP_TEMPLATE = """\
SELECT
    COUNT(*)                                        AS total,
    SUM(CASE WHEN {col} >= $3 THEN 1 ELSE 0 END)   AS successes,
    AVG({col}::float)                               AS mean_val
FROM player_stats
WHERE player_id = $1
  AND season    >= $2
  AND {col} IS NOT NULL
"""

class PropQueryBuilder:
    @classmethod
    def build(cls, params: PropParams) -> tuple[str, tuple[object, ...]]:
        col = PROP_COLUMN_MAP[params.prop_type]   # allowlist, not user input
        sql = _NFL_PROP_TEMPLATE.format(col=col)  # safe — col from static dict
        args: list[object] = [params.player_id, params.season, float(params.line)]
        next_idx = 4
        for key, value in params.filters.items():
            if key not in PROP_ALLOWED_FILTER_KEYS:
                log.warning("unknown_prop_filter_key_dropped", key=key)
                continue
            sql = sql + f"  AND {key} = ${next_idx}\n"
            args.append(value)
            next_idx += 1
        return sql, tuple(args)
```

### run_prop_query — Executor

```python
# src/sportsbet/prop/executor.py (to be created)
# Source: mirrors quant/executor.py verified pattern

MIN_PROP_SAMPLE_SIZE: int = 30

async def run_prop_query(pool: asyncpg.Pool, params: PropParams) -> PropResult:
    sql, args = PropQueryBuilder.build(params)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)

    total = int(row["total"]) if row and row["total"] else 0
    successes = int(row["successes"]) if row and row["successes"] else 0

    if total < MIN_PROP_SAMPLE_SIZE:
        return PropResult(data_source="insufficient_sample", sample_size=total)

    lo, hi = proportion_confint(count=successes, nobs=total, alpha=0.05, method="wilson")
    true_prob = Decimal(str(round(successes / total, 6)))
    ci = (Decimal(str(round(lo, 6))), Decimal(str(round(hi, 6))))
    mean_val = Decimal(str(round(float(row["mean_val"]), 2))) if row["mean_val"] else None

    return PropResult(
        true_probability=true_prob,
        sample_size=total,
        confidence_interval=ci,
        data_source="postgresql",
        mean_stat=mean_val,
    )
```

### GraphState Extension

```python
# src/sportsbet/graph/state.py — add at END of GraphState TypedDict
# Source: Phase 6 pattern for kinematic_result field addition

from sportsbet.graph.models import ContextSignals, PropResult  # runtime import
from sportsbet.kinematic.models import KinematicAnalysis

class GraphState(TypedDict):
    # ... existing fields ...
    prop_result: Optional[PropResult]  # Set by make_prop_quant_agent (Phase 11)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 3 QueryBuilder queries `play_by_play` for team-level win rates | Phase 11 PropQueryBuilder queries `player_stats` for player-level game stat distributions | Phase 11 (now) | Different table, different query shape — `player_stats` rows are per-(player, season, week) not per-play |
| Kinematic signal as standalone pipeline (`kinematic_agent -> END`) | Kinematic signal used as post-query PropResult adjustment | Phase 11 (now) | KinematicAnalysis now consumed downstream — first phase where kinematic output affects another agent's result |

**Deprecated/outdated:**
- `press_man_rate` in `KinematicAnalysis`: ALWAYS `None` in v1. Never read it for kinematic adjustment. Phase 6 decision confirmed: "press_man_rate=None always on KinematicAnalysis — column is NULL in all current ngs_stats rows".

---

## Open Questions

1. **prop_type coverage gap: `completions`, `attempts`, `carries`, `targets`**
   - What we know: `PropParams.prop_type` Literal does NOT include `completions`, `attempts`, `carries`, `targets` — only `pass_yds`, `pass_tds`, `rush_yds`, `rush_tds`, `rec_yds`, `rec_tds`, `receptions`
   - What's unclear: PROP-03 requirement text lists `completions`, `attempts`, `targets` as required prop types
   - Recommendation: Add `completions`, `attempts`, `carries`, `targets` to `PropParams.prop_type` Literal in `graph/models.py` as part of Phase 11 Plan 01. The `player_stats` table has all these columns. This is a backward-compatible model change (new Literal values only).

2. **prop_result field in GraphState: routing integration**
   - What we know: `GraphState` needs a `prop_result` field; `request_type = "prop_analysis"` needs a routing edge
   - What's unclear: Whether to add `prop_analysis` routing in the existing `route_from_master()` in `router.py` now (Phase 11) or defer to Phase 13 (pipeline wiring)
   - Recommendation: Add `prop_result: Optional[PropResult]` to `GraphState` and add `"prop_analysis"` conditional edge in Phase 11. This unblocks Phase 13 pipeline wiring and validates the end-to-end path. Low coupling — router change is one-line.

3. **Kinematic boost magnitude calibration**
   - What we know: `KINEMATIC_BOOST = Decimal("0.05")` is a heuristic (5 pp). No historical calibration data exists yet.
   - What's unclear: Whether 5 pp is the right magnitude without backtesting
   - Recommendation: Hardcode at module level (like `SEPARATION_THRESHOLD = Decimal("2.5")` in `matchup.py`) and document explicitly as uncalibrated heuristic. Phase 8's `BacktestEngine` is the right tool for future calibration.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ with pytest-asyncio |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| Quick run command | `pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x --tb=short` |
| Full suite command | `pytest tests/ -x --tb=short` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-03 | PropQueryBuilder rejects malformed PropParams before SQL | unit | `pytest tests/test_prop_query_builder.py::test_invalid_prop_type_rejected -x` | Wave 0 |
| PROP-03 | PropQueryBuilder produces `$1/$2/$3` positional params only — no user values in SQL string | unit | `pytest tests/test_prop_query_builder.py::test_parameterized_sql -x` | Wave 0 |
| PROP-03 | `run_prop_query` with mock pool returning 50 rows returns `PropResult` with `true_probability` as `Decimal` and `confidence_interval` as `tuple[Decimal, Decimal]` | unit | `pytest tests/test_prop_executor.py::test_adequate_sample -x` | Wave 0 |
| PROP-03 | `run_prop_query` with mock pool returning 5 rows returns `PropResult(data_source="insufficient_sample", true_probability=None)` | unit | `pytest tests/test_prop_executor.py::test_insufficient_sample -x` | Wave 0 |
| PROP-03 | Live PostgreSQL: `run_prop_query` for a known player/season returns non-None `true_probability` | integration | `pytest tests/test_prop_executor.py::test_live_db -x` (skipif no DB) | Wave 0 |
| PROP-04 | Kinematic adjustment applied when `geometric_mismatch_flag=True` and `prop_type="rec_yds"` | unit | `pytest tests/test_prop_executor.py::test_kinematic_adjustment_applied -x` | Wave 0 |
| PROP-04 | Kinematic adjustment NOT applied for `prop_type="pass_yds"` | unit | `pytest tests/test_prop_executor.py::test_kinematic_no_adjust_pass_prop -x` | Wave 0 |
| PROP-04 | Adjusted `true_probability` stays within `[0.01, 0.99]` | unit | `pytest tests/test_prop_executor.py::test_kinematic_probability_clamped -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x --tb=short`
- **Per wave merge:** `pytest tests/ -x --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_prop_query_builder.py` — covers PROP-03 (SQL gate, parameterization, filter allowlist)
- [ ] `tests/test_prop_executor.py` — covers PROP-03 (adequate/insufficient sample, Decimal wrapping) and PROP-04 (kinematic adjustment)
- [ ] `src/sportsbet/prop/__init__.py` — new subpackage marker
- [ ] `src/sportsbet/prop/query_builder.py` — PropQueryBuilder implementation
- [ ] `src/sportsbet/prop/executor.py` — run_prop_query implementation
- [ ] `src/sportsbet/prop/agents.py` — make_prop_quant_agent closure

*(Existing `tests/test_prop_models.py` covers PropParams/PropResult and is already 5/5 green — no changes needed)*

---

## Sources

### Primary (HIGH confidence)

- `src/sportsbet/quant/query_builder.py` — QueryBuilder pattern (ALLOWED_FILTER_KEYS frozenset, $N positional params, static templates) verified from codebase
- `src/sportsbet/quant/executor.py` — Wilson CI pattern, MIN_SAMPLE_SIZE=30, Decimal wrapping verified from codebase
- `src/sportsbet/kinematic/models.py` — KinematicAnalysis fields (`avg_separation`, `geometric_mismatch_flag`, `press_man_rate=None always`) verified from codebase
- `src/sportsbet/graph/models.py` — PropParams Literal union (confirmed: `pass_yds`, `pass_tds`, `rush_yds`, `rush_tds`, `rec_yds`, `rec_tds`, `receptions`) verified from codebase
- `src/sportsbet/db/models.py` — `player_stats` table columns confirmed: `passing_yards`, `passing_tds`, `completions`, `attempts`, `rushing_yards`, `rushing_tds`, `carries`, `receptions`, `targets`, `receiving_yards`, `receiving_tds` — all required PROP-03 stat columns present
- `.planning/STATE.md` decisions — Phase 3, 6, and 10 locked decisions verified

### Secondary (MEDIUM confidence)

- asyncpg documentation pattern for `SMALLINT >= float($N)` comparisons — standard PostgreSQL implicit casting; no special handling needed beyond passing `float(params.line)`
- statsmodels `proportion_confint` with `method="wilson"` — verified in Phase 3 implementation and passing tests

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and in use in prior phases
- Architecture: HIGH — PropQueryBuilder and executor are direct structural analogues of Phase 3 quant/ components; patterns verified from codebase
- Pitfalls: HIGH — items 1-3 verified from Phase 3 decisions in STATE.md; items 4-7 are direct inferences from known constraints
- Kinematic integration: MEDIUM-HIGH — design pattern is clear; boost magnitude is heuristic (documented)

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain — no external API changes; internal codebase is the primary source)
