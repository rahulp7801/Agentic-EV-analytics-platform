# Phase 12: NBA Player Prop Quant Engine - Research

**Researched:** 2026-03-22
**Domain:** NBA player prop statistical distributions; pace adjustment; opponent defensive rating weighting; back-to-back rest penalty; PRA and double-double composite props; NBAQuantAgent closure factory; GraphState extension
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-05 | System calculates true probability for NBA player props (points, rebounds, assists, 3PM, steals, blocks, PRA, double-double) using pace-adjusted historical distributions with opponent defensive rating, rest days, and home/away context | `nba_player_stats` table (season-aggregate totals) exists from Phase 10; `PropParams.prop_type` Literal already includes "points", "rebounds", "assists", "threes", "steals", "blocks", "pra" — "double_double" must be added; pace adjustment, defensive rating weighting, and rest penalty are applied as post-query probability modifiers, not SQL joins, because `nba_player_stats` is season-aggregate (no game-level rows for per-game context) |
| NBA-02 | System applies pace adjustment, back-to-back rest penalty, and opponent defensive rating weighting to NBA player prop probability distributions | Pace factor and defensive rating are floating-point multipliers applied to raw frequency probability after Wilson CI is computed; rest penalty is a fixed subtractive Decimal applied when rest_days == 0 (back-to-back); all three adjustments are bounded to [0.01, 0.99] after application |
</phase_requirements>

---

## Summary

Phase 12 builds the NBA-sport analogue to Phase 11's NFL PropQuantAgent. The structural pattern is identical: `PropParams (Pydantic gate) -> NBAQueryBuilder -> asyncpg parameterized SQL -> PropResult` with additional post-query contextual adjustments. The critical difference is the nature of the data: `nba_player_stats` stores **season-aggregate totals** (one row per player per season), not per-game rows. This means "how often did [player] exceed [line] points?" cannot be answered directly from the current schema — the table holds season totals (e.g. `points = 1800` for the whole season), not per-game values.

This is the most important architectural constraint for Phase 12. The current `nba_player_stats` schema supports per-season queries (average points per game = `points / games_played`) but cannot support per-game frequency distributions without either: (a) switching to a per-game API endpoint (`PlayerGameLog`), or (b) treating `points / games_played` as a Gaussian mean and deriving probability via a z-score approach. Given the Phase 10 ingestion uses `LeagueDashPlayerStats` with `per_mode_simple="Totals"`, the per-game distribution approach requires a statistical model rather than a direct frequency count. The recommended approach for Phase 12 is a **Poisson/normal approximation from per-season averages** computed at query time: `avg_per_game = total_stat / games_played`, then use a normal CDF approximation to estimate `P(stat > line)`. This is mathematically sound for counting stats with large N (20+ games per season) and does not require a schema migration or additional API calls.

The three contextual factors — pace adjustment, defensive rating weighting, and rest penalty — are multiplicative/additive modifiers applied after the base probability is computed. They use simplified proxy values (from `PropParams` or a new `NBAContextSignals` model) rather than live API lookups, keeping the pipeline hallucination-free and fully database-sourced. `NBAContextSignals` is a new Pydantic model introduced in Plan 02 to carry `opponent_def_rating`, `pace_factor`, `rest_days`, and `is_home` through GraphState.

**Primary recommendation:** Build `src/sportsbet/prop/nba_query_builder.py` and `src/sportsbet/prop/nba_executor.py` as NBA-specific siblings to the existing NFL prop modules. Use normal distribution approximation (scipy.stats.norm) from season averages. Apply pace, defensive rating, and rest adjustments as bounded post-query modifiers. Introduce `NBAContextSignals` Pydantic model and extend `GraphState` in Plan 02.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncpg` | >=0.29 (installed) | Async PostgreSQL queries for `nba_player_stats` table | Already in use; same pool factory in `db/connection.py`; `$N` positional param pattern locked |
| `pydantic` | >=2.7,<3.0 (installed) | `PropParams` gate (already in `graph/models.py`) + new `NBAContextSignals` model | `ConfigDict(strict=True)` pattern non-negotiable per CLAUDE.md |
| `scipy` | — check installed | `scipy.stats.norm.cdf()` for normal distribution probability | NBA season-aggregate data requires distribution model rather than frequency count; `norm.cdf` is industry-standard for this use case |
| `statsmodels` | >=0.14 (installed) | Wilson CI via `proportion_confint` | Already in use for NFL props; used in NBA executor for double-double/PRA frequency queries where per-game rows are available |
| `decimal` (stdlib) | Python 3.12 | All probability arithmetic; `true_probability`, CI bounds | Hard rule from Phase 3+11: never assign `float` to a `Decimal` Pydantic field |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `structlog` | >=24.1 (installed) | Structured logging in executor and agent | Matches all other agent/executor modules |
| `gc` (stdlib) | — | Not needed in per-query executor | No batch loading; no OOM risk |

### Checking scipy Availability

`scipy` is used in quant/executor.py via statsmodels internally; check if it is directly importable:

```bash
python -c "from scipy.stats import norm; print('scipy ok')"
```

If not installed, fall back to the pure-Python normal CDF approximation or install via `pip install scipy --target site-packages`. The distribution approximation can also be done via the `statistics` module (Python 3.8+) using `statistics.NormalDist`, which is stdlib and requires no external install.

**Recommended alternative if scipy unavailable:** `statistics.NormalDist(mu=avg, sigma=std).cdf(line)` — stdlib, no extra dependency, same semantic.

### No New Mandatory Dependencies

All required libraries should be already in `pyproject.toml`. If `scipy` is not present, `statistics.NormalDist` (stdlib) is the fallback.

### Installation (if scipy needed)

```bash
pip install scipy --target site-packages
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/sportsbet/
├── prop/                              # EXISTS from Phase 11
│   ├── __init__.py                    # EXISTS
│   ├── query_builder.py               # EXISTS — NFL only (PROP_COLUMN_MAP, _NFL_PROP_TEMPLATE)
│   ├── executor.py                    # EXISTS — NFL only (run_prop_query)
│   ├── agents.py                      # EXISTS — make_prop_quant_agent (NFL)
│   ├── nba_query_builder.py           # NEW — NBAQueryBuilder for nba_player_stats
│   ├── nba_executor.py                # NEW — run_nba_prop_query + contextual adjustments
│   └── nba_agents.py                  # NEW — make_nba_quant_agent closure factory
tests/
├── test_nba_prop_query_builder.py     # NEW — NBAQueryBuilder unit tests (TDD)
└── test_nba_prop_executor.py          # NEW — executor + adjustment tests (TDD)
```

### Critical Architectural Decision: Season-Aggregate vs Per-Game Data

**The problem:** `nba_player_stats` stores one row per (player_id, season) with TOTAL stats for the season (e.g. `points = 1800`, `games_played = 72`). This is NOT per-game granularity — it is exactly what `LeagueDashPlayerStats` with `per_mode_simple="Totals"` returns.

**Two valid approaches:**

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| A: Normal distribution from per-game averages | No schema change, works with existing data, statistically sound for N>20 games | Requires estimated std deviation (use CV heuristic); not exact frequency count | **RECOMMENDED for Phase 12** |
| B: Ingest per-game data via PlayerGameLog (per-game endpoint) | Enables exact frequency count (same as NFL pattern); more accurate | Requires new ingestion module, Alembic migration, re-ingestion; out of Phase 12 scope | Deferred |

**Approach A — Normal approximation:**
1. Query: `SELECT points, games_played, ... FROM nba_player_stats WHERE player_id = $1 AND season >= $2`
2. Compute: `avg_per_game = total_stat / games_played`
3. Estimate std deviation using a sport-specific coefficient of variation (CV): `std = avg_per_game * CV_POINTS` (e.g. `CV_POINTS = 0.35` — points have ~35% game-to-game variance in NBA; `CV_REBOUNDS = 0.45`, `CV_ASSISTS = 0.50`)
4. Compute: `true_probability = norm.cdf((avg_per_game - line) / std)` — probability of OVER when line < avg
5. Apply contextual adjustments (pace, defensive rating, rest)

**CV calibration values (documented as heuristics — same approach as KINEMATIC_BOOST in Phase 11):**
- These are reasonable starting estimates based on NBA statistical patterns; Phase 8 BacktestEngine is the right tool for calibration
- `CV_POINTS = Decimal("0.35")` — scoring is moderate-variance
- `CV_REBOUNDS = Decimal("0.45")` — rebounds are higher variance
- `CV_ASSISTS = Decimal("0.50")` — assists are highest variance
- `CV_THREES = Decimal("0.55")` — 3-pointers are high-variance (shooting)
- `CV_STEALS = Decimal("0.65")` — steals are highest variance (low counts)
- `CV_BLOCKS = Decimal("0.65")` — same as steals
- `CV_PRA = Decimal("0.35")` — PRA (sum) is lower variance than components

### Pattern 1: NBAQueryBuilder — Season-Aggregate Query

**What:** Maps `PropParams.prop_type` to `nba_player_stats` column name and constructs a season-aggregate query.
**Key difference from NFL PropQueryBuilder:** NFL queries `player_stats` for per-week rows (N = weeks). NBA queries `nba_player_stats` for per-season rows (N = seasons), returning season totals. The probability model is distribution-based rather than frequency-count-based.

**SQL pattern for basic stat props (points, rebounds, etc.):**

```sql
-- $1 = player_id (integer), $2 = season (integer)
SELECT
    SUM(games_played)   AS total_games,
    SUM(points)         AS total_points,
    AVG(points::float / NULLIF(games_played, 0)) AS avg_per_game
FROM nba_player_stats
WHERE player_id = $1
  AND season >= $2
  AND games_played IS NOT NULL
  AND points IS NOT NULL
```

**Security invariant (identical to Phase 11):**
- Column names (`points`, `rebounds`, etc.) come from a static `NBA_PROP_COLUMN_MAP` dict keyed by `PropParams.prop_type` Literal
- All dynamic values (`player_id`, `season`) are `$N` positional params
- `{col}` substitution is from a static dict — NOT user input

```python
# src/sportsbet/prop/nba_query_builder.py

NBA_PROP_COLUMN_MAP: dict[str, str] = {
    "points":    "points",
    "rebounds":  "rebounds",
    "assists":   "assists",
    "threes":    "threes_made",
    "steals":    "steals",
    "blocks":    "blocks",
    # PRA and double_double handled by composite logic (see Pattern 3)
}

NBA_PROP_CV_MAP: dict[str, Decimal] = {
    "points":   Decimal("0.35"),
    "rebounds": Decimal("0.45"),
    "assists":  Decimal("0.50"),
    "threes":   Decimal("0.55"),
    "steals":   Decimal("0.65"),
    "blocks":   Decimal("0.65"),
}

_NBA_SEASON_TEMPLATE = """\
SELECT
    SUM(games_played)                                        AS total_games,
    SUM({col})                                               AS total_stat,
    AVG({col}::float / NULLIF(games_played, 0))              AS avg_per_game
FROM nba_player_stats
WHERE player_id = $1
  AND season    >= $2
  AND games_played IS NOT NULL
  AND {col} IS NOT NULL
"""
```

**Important:** `player_id` in `nba_player_stats` is `Integer` (not `VARCHAR` like NFL `player_stats`). asyncpg parameter for `$1` must be Python `int`, not `str`. This is a **critical type difference from Phase 11**.

### Pattern 2: PRA Composite Prop

**What:** PRA (Points + Rebounds + Assists) is a composite stat. `nba_player_stats` does not have a `pra` column. It is computed at query time.

```sql
-- PRA composite query
SELECT
    SUM(games_played) AS total_games,
    SUM(points + rebounds + assists) AS total_pra,
    AVG((points + rebounds + assists)::float / NULLIF(games_played, 0)) AS avg_pra_per_game
FROM nba_player_stats
WHERE player_id = $1
  AND season >= $2
  AND games_played IS NOT NULL
  AND points IS NOT NULL
  AND rebounds IS NOT NULL
  AND assists IS NOT NULL
```

Use `CV_PRA = Decimal("0.35")` — sum variance is lower than individual component variance (diversification effect).

### Pattern 3: double_double Prop

**What:** A double-double is achieved when a player records >= 10 in two or more stat categories (points, rebounds, assists, steals, blocks) in a single game. This is a binary event per game — it CANNOT be computed from season totals without per-game data.

**Recommended approach for v1:** Use a conditional probability estimate from averages. A player's double-double rate can be approximated as `P(PTS >= 10) * P(REB >= 10) + P(PTS >= 10) * P(AST >= 10) + P(REB >= 10) * P(AST >= 10)` using the same normal CDF approach for each component. This is a rough approximation (assumes independence, which is not strictly true) but is far better than no estimate and is explicitly documented as a v1 heuristic.

**SQL for double_double:**
Use the PRA-style query fetching points, rebounds, and assists averages for all seasons in range, then apply the conditional probability formula in Python.

```sql
SELECT
    SUM(games_played) AS total_games,
    AVG(points::float / NULLIF(games_played, 0))   AS avg_pts,
    AVG(rebounds::float / NULLIF(games_played, 0)) AS avg_reb,
    AVG(assists::float / NULLIF(games_played, 0))  AS avg_ast
FROM nba_player_stats
WHERE player_id = $1
  AND season >= $2
  AND games_played IS NOT NULL
```

Then in Python:
```python
LINE_DD = Decimal("10.0")  # double-double threshold
p_pts_10 = norm_cdf_over(avg_pts, std_pts, float(LINE_DD))
p_reb_10 = norm_cdf_over(avg_reb, std_reb, float(LINE_DD))
p_ast_10 = norm_cdf_over(avg_ast, std_ast, float(LINE_DD))
# P(double-double) = P(any two >= 10): use inclusion-exclusion approximation
p_dd = p_pts_10 * p_reb_10 + p_pts_10 * p_ast_10 + p_reb_10 * p_ast_10 - 2 * p_pts_10 * p_reb_10 * p_ast_10
```

Document explicitly as a heuristic approximation in module docstring.

**PropParams.prop_type extension:** `"double_double"` must be added to the Literal union in `graph/models.py`. This is a backward-compatible addition (new value only).

### Pattern 4: Contextual Adjustment Pipeline (NBA-02)

Three adjustments applied sequentially after base `true_probability` is computed:

```
base_prob -> pace_adjust -> def_rating_adjust -> rest_penalty -> clamped [0.01, 0.99]
```

**Pace adjustment:**
- Rationale: Teams playing faster (higher pace = more possessions) generate more scoring opportunities. A 10% faster pace increases player counting stat opportunities by ~10%.
- Formula: `pace_adjusted = base_prob * (team_pace / LEAGUE_AVG_PACE)`
- `LEAGUE_AVG_PACE = Decimal("100.0")` (approximately 100 possessions per 48 min in modern NBA — actual league average is approximately 99-102; use 100 as normalized baseline)
- `team_pace` comes from `NBAContextSignals.pace_factor` passed through GraphState
- Only applied to counting stat props (points, rebounds, assists, PRA) — NOT to rate-based props like 3PM percentage
- Bounded: `max(Decimal("0.5"), min(Decimal("1.5"), pace_ratio))` before multiplication — prevent extreme pace outliers

**Opponent defensive rating adjustment:**
- Rationale: Facing a top-5 defensive team (e.g. def_rating = 105) vs bottom-5 (def_rating = 118) materially changes scoring probability.
- Formula: `def_adjusted = pace_adjusted * (LEAGUE_AVG_DEF_RATING / opponent_def_rating)`
- `LEAGUE_AVG_DEF_RATING = Decimal("115.0")` (points allowed per 100 possessions; league average 2024-25 is approximately 113-116)
- Higher def_rating = worse defense = more scoring opportunity = probability increases
- `opponent_def_rating` comes from `NBAContextSignals.opponent_def_rating`
- Bounded: `max(Decimal("0.7"), min(Decimal("1.3"), def_ratio))` before multiplication

**Back-to-back rest penalty (rest_days == 0):**
- Rationale: NBA players on zero rest (back-to-back games) show measurable performance decline. Published research shows ~2-4% decline in efficiency on back-to-backs. Use a conservative 3% penalty.
- Formula: `rest_adjusted = def_adjusted - REST_PENALTY` when `rest_days == 0`
- `REST_PENALTY = Decimal("0.03")` — 3 percentage point reduction in true probability
- Applied only when `NBAContextSignals.rest_days == 0`
- `rest_days == 1` or `rest_days >= 2`: no adjustment
- Document as heuristic (same language as KINEMATIC_BOOST)

**Home/away context:**
- Rationale: NBA home court advantage is well-documented. However, for player props specifically (vs game props), the effect is smaller and more player-dependent. For v1: apply a small 1.5% boost for home games.
- Formula: `home_adjusted = rest_adjusted + HOME_BOOST` when `is_home == True`
- `HOME_BOOST = Decimal("0.015")` — 1.5 percentage point increase for home games
- Document as heuristic

**Final clamping:** `max(Decimal("0.01"), min(Decimal("0.99"), final_adjusted))`

### Pattern 5: NBAContextSignals Pydantic Model (Plan 02)

New model to be added to `graph/models.py`:

```python
class NBAContextSignals(BaseModel):
    """NBA-specific contextual signals for player prop probability adjustment.

    Carries pace, defensive rating, rest days, and home/away context
    through GraphState for consumption by make_nba_quant_agent.

    All values are caller-supplied (from live data or fixture inputs) —
    never inferred by LLM.
    """
    model_config = ConfigDict(strict=True)

    opponent_def_rating: Decimal     # Opponent's defensive rating (points/100 possessions)
    pace_factor: Decimal             # Team's pace (possessions per 48 min)
    rest_days: int                   # Days since last game (0 = back-to-back)
    is_home: bool                    # True if player's team is the home team
```

### Pattern 6: make_nba_quant_agent Closure Factory

Mirrors `make_prop_quant_agent` exactly. Additional GraphState fields consumed:
- `nba_context_signals: Optional[NBAContextSignals]` — new GraphState field added in Plan 02
- `prop_type: str` — already in GraphState via prop_quant_agent path
- `prop_line: float | int | None` — already in GraphState

**Pipeline:**
1. Extract `PropParams` fields from `GraphState` (sport="nba")
2. Extract `NBAContextSignals` from `state.get("nba_context_signals")`
3. Validate via `PropParams(...)` — raises `ValidationError` on malformed input
4. Call `run_nba_prop_query(pool, params)` — returns base `PropResult`
5. Call `_apply_nba_context_adjustments(result, context_signals, params.prop_type)` — applies pace/def/rest/home adjustments
6. Return `{"nba_prop_result": result}`

**Routing:** `request_type = "nba_prop_analysis"` routes to `nba_quant_agent` node (new conditional edge in `router.py`).

**GraphState extensions for Plan 02:**
- `nba_context_signals: Optional[NBAContextSignals]` — new field, runtime import (not TYPE_CHECKING), follows Phase 4/6 pattern
- `nba_prop_result: Optional[PropResult]` — new field, same import pattern

### Anti-Patterns to Avoid

- **Querying `player_stats` (NFL table) for NBA props:** `player_stats` is the NFL weekly stats table. NBA data is in `nba_player_stats`. Different tables, different schemas, different `player_id` types (str vs int).
- **Treating `nba_player_stats.points` as per-game values:** The column stores season totals. Always divide by `games_played` to get per-game averages before computing probability.
- **Using Wilson CI for normal approximation:** Wilson CI is for proportion (successes/total with known N). When using normal approximation from averages, use `norm.cdf()` (or `NormalDist.cdf()`), not `proportion_confint`.
- **asyncpg type error: player_id must be int for NBA:** `nba_player_stats.player_id` is `Integer` in the ORM. Pass Python `int` to asyncpg `$1`. Unlike NFL `player_stats.player_id` which is `VARCHAR(20)`.
- **Float assigned to strict Decimal field:** Same as Phases 3 and 11. Always `Decimal(str(round(x, 6)))`.
- **Applying pace/def adjustments without bounds:** Unbounded adjustments can push probability outside [0,1]. Always clamp pace_ratio and def_ratio before multiplying, and clamp final result to [0.01, 0.99].
- **Applying rest penalty to aggregate historical distributions:** The normal distribution is built from multi-season averages (which already average across rest conditions). The rest_penalty is an additional forward-looking adjustment on top of the historical baseline — this is correct and intentional.
- **double_double prop without the independence approximation caveat:** Pts, Reb, Ast are correlated (star players tend to have high averages in multiple categories). Document the independence assumption explicitly as a v1 heuristic.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Normal distribution CDF | Custom probability formula | `statistics.NormalDist(mu, sigma).cdf(line)` (stdlib) or `scipy.stats.norm.cdf` | Handles edge cases; stdlib NormalDist is dependency-free |
| Standard deviation estimation | Manual formula | `std = avg * CV_MAP[prop_type]` — calibrated coefficient of variation | Simpler than ML model; documents heuristic nature explicitly |
| Pydantic model for NBA context | New custom dict | `NBAContextSignals(BaseModel)` with `ConfigDict(strict=True)` | Enforces types; prevents LLM hallucination on numeric fields |
| NBA player_id type handling | Manual casting | Verify `int(params.player_id)` or store player_id as str in PropParams and cast at query time | asyncpg is strict on types; `nba_player_stats.player_id` is INTEGER |
| SQL injection prevention | String escaping | asyncpg `$N` params + static `NBA_PROP_COLUMN_MAP` allowlist | Same structural prevention as `quant/query_builder.py` and `prop/query_builder.py` |

---

## Common Pitfalls

### Pitfall 1: Season-Aggregate Data Misread as Per-Game

**What goes wrong:** Query returns `points = 1800` for a player. Code treats this as 1800 points per game (i.e., always over any reasonable line), returning `true_probability = 0.99`.
**Why it happens:** `nba_player_stats` stores season totals (`per_mode_simple="Totals"` in ingestion). The column name `points` looks like per-game but it is the season total.
**How to avoid:** Always compute `avg_per_game = total_points / games_played` before any probability computation. Add an assertion in the executor: `assert games_played > 0`.
**Warning signs:** `true_probability` always near 1.0 or 0.0 for all players; `avg_per_game` values in the thousands.

### Pitfall 2: player_id Type Mismatch (int vs str)

**What goes wrong:** `await conn.fetchrow(sql, params.player_id, season)` where `params.player_id` is a Python `str` like `"203076"` raises `asyncpg.exceptions._base.InterfaceError` because `nba_player_stats.player_id` is `INTEGER`.
**Why it happens:** `PropParams.player_id` is `str` (shared with NFL). NBA player IDs from `nba_api` are integers (e.g. `203076`).
**How to avoid:** Cast at query construction time: `int(params.player_id)` as the `$1` arg in `NBAQueryBuilder.build()`. Document this cast explicitly in the query builder docstring.
**Warning signs:** `asyncpg.exceptions._base.InterfaceError: cannot convert 'str' to 'int4'`.

### Pitfall 3: Wilson CI Used Instead of Normal CDF

**What goes wrong:** Developer copies `proportion_confint(count=successes, nobs=total, method="wilson")` from `prop/executor.py` into the NBA executor. With season-aggregate data there are no `successes/total` counts — there is one row per season.
**Why it happens:** Pattern copy from NFL executor without recognizing the data model difference.
**How to avoid:** NBA executor uses `statistics.NormalDist(mu=avg_per_game, sigma=std).cdf(line)`. Wilson CI is only used if per-game rows become available in a future phase. Document this distinction in the module docstring.

### Pitfall 4: Games Played = 0 Division

**What goes wrong:** `avg_per_game = total_stat / games_played` raises `ZeroDivisionError` when a player has 0 games played (can happen for injured players or recently signed players with no data).
**Why it happens:** The SQL query may return a row with `games_played = 0` or NULL.
**How to avoid:** Gate on `total_games < MIN_SAMPLE_GAMES` before any computation. Use `NULLIF(games_played, 0)` in the SQL `AVG()` computation. Return `PropResult(data_source="insufficient_sample")` when `total_games < MIN_SAMPLE_GAMES`.
**Recommended gate:** `MIN_SAMPLE_GAMES: int = 20` — minimum 20 career games across queried seasons before applying the distribution model.

### Pitfall 5: Std Dev = 0 for Star Players with High CV

**What goes wrong:** `std = avg_per_game * CV` where `avg_per_game = 0.0` (player never scores) produces `std = 0.0`, which causes `NormalDist(mu=0, sigma=0)` to raise `StatisticsError: sigma must be positive`.
**Why it happens:** Some players have zero averages for specific stats (e.g. a center with 0 assists).
**How to avoid:** Add a floor: `std = max(0.5, avg_per_game * float(CV))`. The floor of 0.5 prevents zero-sigma and represents approximately the minimum meaningful statistical variance for NBA counting stats.

### Pitfall 6: Pace Adjustment Applied to 3PM Prop

**What goes wrong:** `3PM` (threes made) probability is boosted by a pace multiplier, but the pace multiplier is intended for volume/counting stats. 3-point shooting rate is more skill-based than pace-dependent in a player prop context.
**Why it happens:** `pace_adjustment` applied uniformly to all prop types.
**How to avoid:** Define `PACE_ADJUSTED_PROPS: frozenset[str]` limiting pace adjustment to `{"points", "rebounds", "assists", "pra"}`. `"threes"`, `"steals"`, `"blocks"`, `"double_double"` are skill-rate props — pace adjustment adds noise rather than signal.

### Pitfall 7: TYPE_CHECKING Import for NBAContextSignals in state.py

**What goes wrong:** Adding `from sportsbet.graph.models import NBAContextSignals` under `if TYPE_CHECKING:` causes LangGraph's `get_type_hints(GraphState)` to fail with `NameError: name 'NBAContextSignals' is not defined`.
**Why it happens:** Same pitfall documented in Phase 4 (ContextSignals) and Phase 6 (KinematicAnalysis).
**How to avoid:** Import `NBAContextSignals` at runtime in `state.py` — NOT under `TYPE_CHECKING`. This is the locked pattern for all GraphState model imports. See Phase 4 decision: "ContextSignals imported at runtime in state.py (not TYPE_CHECKING) — LangGraph calls get_type_hints(GraphState)".

### Pitfall 8: double_double Prop Type Missing from PropParams Literal

**What goes wrong:** `PropParams(prop_type="double_double")` raises `ValidationError: Input should be 'pass_yds' | 'pass_tds' | ...` because `"double_double"` is not in the current Literal union.
**Why it happens:** Phase 10 defined the Literal union without `double_double`. Phase 12 requires it.
**How to avoid:** Add `"double_double"` to `PropParams.prop_type` Literal in `graph/models.py`. This is backward-compatible (new Literal value). Must also update `PROP_COLUMN_MAP` in `prop/query_builder.py` to include `"double_double": "double_double"` (forwarded to NBA query path, not handled by `_NFL_PROP_TEMPLATE`).

---

## Code Examples

Verified patterns from codebase inspection:

### NBAQueryBuilder — Core Build Method

```python
# src/sportsbet/prop/nba_query_builder.py (to be created)
# Source: mirrors prop/query_builder.py pattern; verified against db/models.py NBAPlayerStats schema

from decimal import Decimal
from sportsbet.graph.models import PropParams

NBA_PROP_COLUMN_MAP: dict[str, str] = {
    "points":   "points",
    "rebounds": "rebounds",
    "assists":  "assists",
    "threes":   "threes_made",
    "steals":   "steals",
    "blocks":   "blocks",
    # PRA and double_double use composite queries — not single-column templates
}

NBA_PROP_CV_MAP: dict[str, Decimal] = {
    "points":    Decimal("0.35"),
    "rebounds":  Decimal("0.45"),
    "assists":   Decimal("0.50"),
    "threes":    Decimal("0.55"),
    "steals":    Decimal("0.65"),
    "blocks":    Decimal("0.65"),
    "pra":       Decimal("0.35"),
    "double_double": Decimal("0.40"),  # composite — uses pts/reb/ast CDF combination
}

PACE_ADJUSTED_PROPS: frozenset[str] = frozenset({"points", "rebounds", "assists", "pra"})

_NBA_SINGLE_STAT_TEMPLATE = """\
SELECT
    SUM(games_played) AS total_games,
    SUM({col})        AS total_stat,
    AVG({col}::float / NULLIF(games_played, 0)) AS avg_per_game
FROM nba_player_stats
WHERE player_id = $1
  AND season    >= $2
  AND games_played IS NOT NULL
  AND {col} IS NOT NULL
"""

_NBA_PRA_TEMPLATE = """\
SELECT
    SUM(games_played) AS total_games,
    SUM(points + rebounds + assists) AS total_stat,
    AVG((points + rebounds + assists)::float / NULLIF(games_played, 0)) AS avg_per_game
FROM nba_player_stats
WHERE player_id = $1
  AND season    >= $2
  AND games_played IS NOT NULL
  AND points IS NOT NULL
  AND rebounds IS NOT NULL
  AND assists IS NOT NULL
"""

_NBA_DD_TEMPLATE = """\
SELECT
    SUM(games_played) AS total_games,
    AVG(points::float  / NULLIF(games_played, 0)) AS avg_pts,
    AVG(rebounds::float / NULLIF(games_played, 0)) AS avg_reb,
    AVG(assists::float / NULLIF(games_played, 0)) AS avg_ast
FROM nba_player_stats
WHERE player_id = $1
  AND season    >= $2
  AND games_played IS NOT NULL
"""

class NBAQueryBuilder:
    @classmethod
    def build(cls, params: PropParams) -> tuple[str, tuple[object, ...]]:
        # player_id must be int for nba_player_stats.player_id (INTEGER column)
        player_id_int: int = int(params.player_id)  # explicit cast; documented in docstring
        args: tuple[object, ...] = (player_id_int, params.season)

        if params.prop_type == "pra":
            return _NBA_PRA_TEMPLATE, args
        if params.prop_type == "double_double":
            return _NBA_DD_TEMPLATE, args

        # Single-stat props
        col = NBA_PROP_COLUMN_MAP[params.prop_type]  # allowlist, not user input
        sql = _NBA_SINGLE_STAT_TEMPLATE.format(col=col)  # safe — col from static dict
        return sql, args
```

### run_nba_prop_query — Executor

```python
# src/sportsbet/prop/nba_executor.py (to be created)
# Source: mirrors prop/executor.py; uses statistics.NormalDist instead of proportion_confint

from statistics import NormalDist
from decimal import Decimal

MIN_SAMPLE_GAMES: int = 20  # minimum career games for reliable distribution

async def run_nba_prop_query(pool: asyncpg.Pool, params: PropParams) -> PropResult:
    sql, args = NBAQueryBuilder.build(params)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)

    total_games = int(row["total_games"]) if row and row["total_games"] else 0
    if total_games < MIN_SAMPLE_GAMES:
        return PropResult(data_source="insufficient_sample", sample_size=total_games)

    line = float(params.line)
    cv = NBA_PROP_CV_MAP.get(params.prop_type, Decimal("0.40"))

    if params.prop_type == "double_double":
        true_prob = _compute_double_double_prob(row, float(cv))
    else:
        avg = float(row["avg_per_game"]) if row["avg_per_game"] else 0.0
        std = max(0.5, avg * float(cv))
        dist = NormalDist(mu=avg, sigma=std)
        # P(stat > line) = 1 - CDF(line)
        true_prob_float = 1.0 - dist.cdf(line)
        true_prob_float = max(0.01, min(0.99, true_prob_float))
        true_prob = Decimal(str(round(true_prob_float, 6)))

    return PropResult(
        true_probability=true_prob,
        sample_size=total_games,
        confidence_interval=None,  # CI not computable from normal approximation without per-game rows
        data_source="postgresql+normal_approx",
        mean_stat=Decimal(str(round(float(row.get("avg_per_game", 0) or 0), 2))),
    )
```

### NBAContextSignals Model

```python
# src/sportsbet/graph/models.py — new class to add at end of file

class NBAContextSignals(BaseModel):
    """NBA-specific context for player prop probability adjustment.

    All fields are caller-supplied — never inferred by LLM.
    Passed through GraphState.nba_context_signals to make_nba_quant_agent.
    """
    model_config = ConfigDict(strict=True)

    opponent_def_rating: Decimal  # Points allowed per 100 possessions (e.g. Decimal("112.5"))
    pace_factor: Decimal          # Team possessions per 48 min (e.g. Decimal("101.3"))
    rest_days: int                # Days since last game (0 = back-to-back)
    is_home: bool                 # True when player's team is home
```

### GraphState Extension (Plan 02)

```python
# src/sportsbet/graph/state.py — add at END of GraphState TypedDict and imports
# Source: Phase 4/6 pattern for runtime import (not TYPE_CHECKING)

from sportsbet.graph.models import ContextSignals, PropResult, NBAContextSignals

class GraphState(TypedDict):
    # ... existing fields ...
    nba_context_signals: Optional[NBAContextSignals]  # Set by caller for NBA prop queries (Phase 12)
    nba_prop_result: Optional[PropResult]              # Set by make_nba_quant_agent (Phase 12)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 11 PropQueryBuilder queries `player_stats` for per-game weekly rows (frequency count) | Phase 12 NBAQueryBuilder queries `nba_player_stats` for season-aggregate totals; uses normal distribution approximation | Phase 12 (now) | Different statistical model: frequency count -> normal CDF from mean/CV; no per-game rows available |
| No NBA-specific contextual signals in GraphState | `NBAContextSignals` model + `nba_context_signals` GraphState field | Phase 12 (now) | Pace/defensive rating/rest/home context flows through state without LLM inference |
| `PropParams.prop_type` Literal missing `"double_double"` | Add `"double_double"` to Literal in `graph/models.py` | Phase 12 (now) | Backward-compatible extension; also update `PROP_COLUMN_MAP` forward-compat entry |

**Deprecated/outdated:**
- `nba_player_stats` `"pra"` column: The `PROP_COLUMN_MAP` in `prop/query_builder.py` maps `"pra": "pra"` as a comment "not handled by `_NFL_PROP_TEMPLATE`". The NBA executor must implement PRA via the composite SQL template, NOT by querying a `pra` column that does not exist in the ORM.

---

## Open Questions

1. **scipy vs statistics.NormalDist**
   - What we know: `statistics.NormalDist` (Python 3.8+ stdlib) provides `cdf()` method — no external dependency. `scipy.stats.norm.cdf()` is the industry standard but requires scipy install.
   - What's unclear: Whether scipy is already installed (statsmodels may pull it in as a dependency)
   - Recommendation: Use `statistics.NormalDist` — zero-dependency stdlib approach. If scipy is confirmed installed (`python -c "import scipy"` succeeds), either works. Prefer stdlib to avoid dependency drift.

2. **CV calibration values accuracy**
   - What we know: CV values (0.35 for points, 0.45 for rebounds, etc.) are heuristic starting points consistent with known NBA statistical patterns.
   - What's unclear: Whether these CV values are well-calibrated for the specific player population queried.
   - Recommendation: Document all CVs as uncalibrated heuristics in module docstring (same language as `KINEMATIC_BOOST` and `SEPARATION_THRESHOLD`). Phase 8's `BacktestEngine` is the right tool for future calibration.

3. **confidence_interval for normal approximation**
   - What we know: Wilson CI is not applicable to normal distribution estimates. `PropResult.confidence_interval` will be `None` for NBA props.
   - What's unclear: Whether the Phase 13 PropArbitrageAgent requires a non-None `confidence_interval` to function.
   - Recommendation: Set `confidence_interval=None` and `data_source="postgresql+normal_approx"` so Phase 13 can detect and handle the NBA case. Verify Phase 13's `PropArbitrageAgent` handles `confidence_interval=None` gracefully (it should since `PropResult.confidence_interval` is already `Optional`).

4. **LEAGUE_AVG_PACE and LEAGUE_AVG_DEF_RATING constants**
   - What we know: Current NBA league average pace is approximately 99-102 possessions per 48 minutes (2024-25 season). Defensive rating is approximately 112-116.
   - Recommendation: Use `LEAGUE_AVG_PACE = Decimal("100.0")` and `LEAGUE_AVG_DEF_RATING = Decimal("115.0")` as round-number proxies. Document as "2024-25 season approximations; update annually." These are adjustments to the base probability — precision here matters less than the direction of the adjustment.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ with pytest-asyncio |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| Quick run command | `pytest tests/test_nba_prop_query_builder.py tests/test_nba_prop_executor.py -x --tb=short` |
| Full suite command | `pytest tests/ -x --tb=short` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-05 | `NBAQueryBuilder.build()` produces `$1/$2` positional params only for single-stat prop; `player_id` cast to `int` | unit | `pytest tests/test_nba_prop_query_builder.py::test_nba_parameterized_sql -x` | Wave 0 |
| PROP-05 | `NBAQueryBuilder.build()` uses `_NBA_PRA_TEMPLATE` for `prop_type="pra"` | unit | `pytest tests/test_nba_prop_query_builder.py::test_nba_pra_template -x` | Wave 0 |
| PROP-05 | `NBAQueryBuilder.build()` uses `_NBA_DD_TEMPLATE` for `prop_type="double_double"` | unit | `pytest tests/test_nba_prop_query_builder.py::test_nba_dd_template -x` | Wave 0 |
| PROP-05 | `PropParams(prop_type="double_double")` validates (no ValidationError) after adding to Literal | unit | `pytest tests/test_prop_models.py::test_double_double_prop_type -x` | Wave 0 |
| PROP-05 | `run_nba_prop_query` with mock pool returning season totals computes `true_probability` as `Decimal` | unit | `pytest tests/test_nba_prop_executor.py::test_adequate_sample -x` | Wave 0 |
| PROP-05 | `run_nba_prop_query` with mock pool returning `total_games < 20` returns `PropResult(data_source="insufficient_sample", true_probability=None)` | unit | `pytest tests/test_nba_prop_executor.py::test_insufficient_sample -x` | Wave 0 |
| PROP-05 | PRA query returns `PropResult` with non-None `true_probability` | unit | `pytest tests/test_nba_prop_executor.py::test_pra_result -x` | Wave 0 |
| PROP-05 | double_double query returns statistically valid `PropResult` (probability in [0.01, 0.99]) | unit | `pytest tests/test_nba_prop_executor.py::test_double_double_result -x` | Wave 0 |
| NBA-02 | `rest_days=0` query returns meaningfully lower `true_probability` than `rest_days=2` for same base stats | unit | `pytest tests/test_nba_prop_executor.py::test_rest_penalty_applied -x` | Wave 0 |
| NBA-02 | Pace factor > league average increases `true_probability` for "points" prop | unit | `pytest tests/test_nba_prop_executor.py::test_pace_adjustment_up -x` | Wave 0 |
| NBA-02 | Opponent def_rating below league average decreases `true_probability` for "points" prop | unit | `pytest tests/test_nba_prop_executor.py::test_def_rating_adjustment -x` | Wave 0 |
| NBA-02 | Adjusted `true_probability` stays within `[0.01, 0.99]` after all adjustments | unit | `pytest tests/test_nba_prop_executor.py::test_probability_clamped -x` | Wave 0 |
| NBA-02 | Live PostgreSQL: `run_nba_prop_query` returns non-None `true_probability` for a known player (skipif no DB) | integration | `pytest tests/test_nba_prop_executor.py::test_live_db -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_nba_prop_query_builder.py tests/test_nba_prop_executor.py -x --tb=short`
- **Per wave merge:** `pytest tests/ -x --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_nba_prop_query_builder.py` — covers PROP-05 (SQL gate, parameterization, PRA/DD templates, player_id int cast)
- [ ] `tests/test_nba_prop_executor.py` — covers PROP-05 (adequate/insufficient sample, Decimal wrapping, PRA, double_double) and NBA-02 (pace, def_rating, rest penalty, home boost, clamping)
- [ ] `src/sportsbet/prop/nba_query_builder.py` — NBAQueryBuilder, NBA_PROP_COLUMN_MAP, CV_MAP, templates
- [ ] `src/sportsbet/prop/nba_executor.py` — run_nba_prop_query, NormalDist approximation, contextual adjustments
- [ ] `src/sportsbet/prop/nba_agents.py` — make_nba_quant_agent closure factory
- [ ] `graph/models.py` modification — add `NBAContextSignals` class + `"double_double"` to PropParams Literal
- [ ] `graph/state.py` modification — add `nba_context_signals` and `nba_prop_result` fields
- [ ] `graph/router.py` modification — add `"nba_prop_analysis"` conditional edge
- [ ] `prop/query_builder.py` modification — add `"double_double": "double_double"` to PROP_COLUMN_MAP (forward-compat entry)

*(Existing `tests/test_prop_models.py` — add one test for `prop_type="double_double"` after model update)*
*(Existing `tests/test_prop_query_builder.py` — no changes needed)*

---

## Sources

### Primary (HIGH confidence)

- `src/sportsbet/db/models.py` — `NBAPlayerStats` table schema verified (player_id=Integer, season=SmallInteger, points/rebounds/assists/threes_made/steals/blocks=Integer, games_played=SmallInteger); confirmed NO `pra` column, NO per-game rows
- `src/sportsbet/ingestion/nba.py` — ingestion uses `per_mode_simple="Totals"` confirmed; season-aggregate nature of data verified
- `src/sportsbet/prop/query_builder.py` — PROP_COLUMN_MAP maps `"pra": "pra"` and `"points": "pts"` (note: `"pts"` not `"points"` — this is the PROP_COLUMN_MAP entry for legacy purposes; `nba_player_stats` actually uses column name `points`); verified against ORM — correct column is `points`, not `pts`. The PROP_COLUMN_MAP entry `"points": "pts"` in `query_builder.py` is erroneous for NBA (it maps to NFL's `pts` which does not exist in `player_stats`); NBAQueryBuilder must use `"points": "points"` from `nba_player_stats`
- `src/sportsbet/graph/models.py` — PropParams.prop_type Literal confirmed missing `"double_double"`; `"pra"` IS in the Literal; `NBAContextSignals` does not yet exist
- `src/sportsbet/graph/state.py` — `nba_context_signals` and `nba_prop_result` fields NOT yet in GraphState; confirmed `prop_result: Optional[PropResult]` is the most recent field added (Phase 11)
- `src/sportsbet/prop/agents.py` — `make_prop_quant_agent` closure factory pattern verified; runtime import of `KinematicAnalysis` (not TYPE_CHECKING) confirmed
- `.planning/STATE.md` decisions — Phase 4, 6, 10, 11 locked decisions verified; runtime import pattern for GraphState fields locked

### Secondary (MEDIUM confidence)

- `statistics.NormalDist` Python 3.8+ stdlib documentation — `NormalDist(mu, sigma).cdf(x)` verified interface; returns `P(X <= x)`; `1 - cdf(line)` = `P(stat > line)` for over props
- NBA pace and defensive rating ranges: 2024-25 NBA average pace approximately 99-102 possessions per 48 min; defensive rating approximately 112-116 points per 100 possessions — consistent with publicly available NBA stats summaries

### Tertiary (LOW confidence — marked for validation)

- CV calibration values (`CV_POINTS = 0.35`, etc.) — domain heuristics consistent with NBA scoring variance patterns; not formally calibrated; document as heuristics pending BacktestEngine validation
- Rest penalty magnitude (`REST_PENALTY = 0.03`) — based on published research indicating ~2-4% efficiency decline on back-to-backs; specific 3% value is a round-number approximation
- Home court boost magnitude (`HOME_BOOST = 0.015`) — player prop home advantage is smaller than game-level; 1.5% is conservative estimate

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries either installed (asyncpg, pydantic, statsmodels, structlog) or stdlib (statistics.NormalDist); verified from pyproject.toml and existing codebase
- Architecture: HIGH — data model verified from ORM and ingestion code; season-aggregate constraint is a hard fact from the codebase, not an inference; query patterns follow established Phase 11 structure
- Pitfalls: HIGH — items 1-3 (season-aggregate misread, player_id type, wrong CI method) are directly verifiable from codebase; items 4-8 are direct inferences from known constraints and Phase 11 decisions
- Contextual adjustments: MEDIUM — direction of adjustments (pace up = more scoring, better defense = less scoring, rest=0 = penalty) is well-established; magnitude constants are LOW-confidence heuristics documented as such
- PRA/double_double statistical model: MEDIUM — normal CDF from season averages is sound for N>20; independence assumption for double_double is explicitly a v1 simplification

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain — no external API changes; primary source is the internal codebase)
