# Phase 18: Situational Game-Log Prop Queries - Research

**Researched:** 2026-03-24
**Domain:** Conditional probability via game-log SQL, nba_api PlayerGameLogs ingest, PropParams extension, asyncpg parameterized WHERE construction, Wilson CI small-sample behavior
**Confidence:** HIGH

## Summary

Phase 18 replaces season-aggregate true-probability with game-log-derived conditional probability for both NBA and NFL props. The current NBA path (`nba_player_stats` season totals + NormalDist CDF) and the NFL path (`player_stats` weekly rows + Wilson CI) both ignore conditional context — who was missing, home vs. away, recent form. This phase layers situational filters on top of those existing pipelines without replacing the season-aggregate path, so the two modes coexist cleanly.

The three core changes are: (1) a new `nba_player_gamelogs` table populated by `nba_api.PlayerGameLogs` (all players per season, one HTTP call per season), (2) extending `PropParams` with four optional situational fields (`last_n_games`, `teammate_out`, `opponent_team`, `home_away`) and injecting them via `GraphState`/`ContextAgent`, and (3) rewriting both `PropQueryBuilder` (NFL) and `NBAQueryBuilder` to construct conditional WHERE clauses from those filters using only `asyncpg` positional `$N` params.

The Wilson CI behavior is the critical executor change: the existing `MIN_SAMPLE_SIZE=30` hard gate must be removed or bypassed for conditional queries. Wilson CI in statsmodels works for any `nobs >= 2` (returns valid wide CI); `nobs=0` returns NaN which requires an explicit guard. The solution is a graceful fallback: return `PropResult` with `true_probability` populated but `confidence_interval=None` tagged with `data_source="conditional_small_sample"` for `nobs < 30`, rather than blocking the call entirely.

**Primary recommendation:** Use `nba_api.PlayerGameLogs` (plural, bulk endpoint) for NBA game-log ingest (one call per season instead of one per player); parse the `MATCHUP` column (`@` = away, `vs.` = home) to derive `is_home`; for NFL use the existing `player_stats` weekly rows joined to `games` for opponent and location; for both, construct conditional WHERE clauses via an extended allowlist + positional params pattern already in place.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| nba_api | >=1.11 (already in pyproject.toml) | NBA per-game log ingest via `PlayerGameLogs` endpoint | Already installed; `PlayerGameLogs` bulk endpoint returns all players per season in one call |
| asyncpg | >=0.29 (already installed) | Async PostgreSQL queries with positional `$N` params | Locked project choice for hot-path agent queries |
| statsmodels | >=0.14 (already installed) | Wilson CI via `proportion_confint(..., method="wilson")` | Already in use in `prop/executor.py` |
| SQLAlchemy 2.0 | already installed | ORM model for `NBAPlayerGameLog` table | Locked project choice for all ORM definitions |
| Alembic | >=1.13 (already installed) | Migration 0005 for `nba_player_gamelogs` | Locked project choice; migration must be hand-written (autogenerate omits composite indexes) |
| Pydantic v2 | >=2.7,<3.0 (already installed) | `PropParams` extension with `Optional` fields | Locked; all models use `ConfigDict(strict=True)` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| nflreadpy | >=0.1.5 (already installed) | NFL weekly player stats already have `opponent_team`; schedules needed for `location` | NFL game-log queries can use existing `player_stats` table with new `opponent_team` + `home_away` support joined via `games` table |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `PlayerGameLogs` (bulk, all players/season) | `PlayerGameLog` (singular, per-player per-season) | Per-player call requires one HTTP call per player — 500+ calls per season; bulk is strongly preferred |
| New `nba_player_gamelogs` table | Querying `nba_player_stats` (season totals) | Season totals cannot support conditional game filtering — new table is required |
| Wilson CI with graceful widening for n<30 | Hard `MIN_SAMPLE_SIZE` gate | Hard gate rejects all conditional queries (sample of 5 "Draymond out, away" games is valid — just uncertain) |

**Installation:** No new packages required — `nba_api`, `statsmodels`, `asyncpg`, `SQLAlchemy`, `Alembic`, and `Pydantic` are all already in `pyproject.toml`.

## Architecture Patterns

### Recommended Project Structure

New files added in Phase 18:
```
src/sportsbet/
├── ingestion/
│   └── nba_gamelogs.py          # New: PlayerGameLogs ingest pipeline
├── prop/
│   ├── query_builder.py         # Modified: add situational WHERE clause construction
│   ├── nba_query_builder.py     # Modified: add nba_player_gamelogs templates
│   ├── executor.py              # Modified: remove hard MIN_SAMPLE_SIZE gate for conditional
│   └── nba_executor.py          # Modified: add per-game frequency model for gamelogs
└── graph/
    ├── models.py                # Modified: extend PropParams, add SituationalParams
    └── state.py                 # Modified: add situational_params field to GraphState
alembic/versions/
└── 0005_add_nba_player_gamelogs.py  # New: migration
tests/
├── test_nba_gamelogs_ingest.py     # New: ingest pipeline tests
├── test_situational_prop_params.py # New: PropParams extension tests
└── test_situational_query_builders.py  # New: WHERE clause construction tests
```

### Pattern 1: PlayerGameLogs Bulk Ingest (NBA)

**What:** One `PlayerGameLogs` call per season returns all player-game rows for that season. Parse the `MATCHUP` column to derive `is_home` and `opponent_team`.

**When to use:** Ingest time — not at query time.

**Key columns available from `PlayerGameLogs`:**
- `PLAYER_ID` (int), `PLAYER_NAME`, `TEAM_ABBREVIATION`, `GAME_ID`, `GAME_DATE`, `MATCHUP`, `MIN`, `PTS`, `REB`, `AST`, `FG3M`, `STL`, `BLK`
- `MATCHUP` format: `"LAL vs. GSW"` = LAL is home; `"LAL @ GSW"` = LAL is away

**Example:**
```python
# Source: nba_api.stats.endpoints.PlayerGameLogs (verified from site-packages source)
from nba_api.stats.endpoints import PlayerGameLogs

logs = PlayerGameLogs(
    season_nullable="2023-24",
    season_type_nullable="Regular Season",
    timeout=30,
)
time.sleep(1)  # NBA.com rate limit — mandatory
df = logs.get_data_frames()[0]

# Derive is_home and opponent_team from MATCHUP
df["is_home"] = ~df["MATCHUP"].str.contains("@")
# MATCHUP 'LAL @ BOS' -> opponent='BOS'; 'LAL vs. BOS' -> opponent='BOS'
df["opponent_team"] = df["MATCHUP"].str.split(r" @ | vs\. ").str[-1]
```

### Pattern 2: NFL Game-Log Queries Against Existing `player_stats`

**What:** NFL already stores one row per player per week in `player_stats`. The table has `opponent_team` missing from the current ORM (it's not in the Phase 10 whitelist), but `player_stats` does join to `games` via `game_id` (available in nflreadpy weekly data as part of the `game_id` field — confirmed by nflreadr data dictionary).

**Critical finding:** The existing `player_stats` ORM model does NOT store `opponent_team` or `location` (home/away). These must be JOIN'd from the `games` table using `game_id`. The `player_stats` table currently has no `game_id` column.

**Resolution:** Two options:
- Option A: Add `game_id` and `opponent_team` columns to `player_stats` in migration 0005 — enables direct WHERE filter without JOIN.
- Option B: Build conditional NFL queries as a JOIN between `player_stats` and `games` on `(player_stats.season, player_stats.week, player_stats.team)`.

**Recommendation:** Option A is cleaner — add `game_id` (nullable String), `opponent_team` (nullable String(3)), and `home_away` (nullable String(4)) to `player_stats` in migration 0005. The nflreadpy weekly player stats data dictionary confirms `opponent_team` is available in the raw data (already confirmed from nflreadr documentation). The `home_away` can be derived from `games` schedule data via `load_schedules()` which provides `home_team`/`away_team`.

**Important caveat:** If adding columns to `player_stats` is considered too disruptive, the JOIN path (Option B) is viable but requires a more complex SQL template. The plan should decide this.

### Pattern 3: PropParams Situational Filter Extension

**What:** Add four `Optional` fields to `PropParams` (all with `None` default). Since `PropParams` uses `ConfigDict(strict=True)`, Optional fields with defaults are accepted.

**Example:**
```python
# Source: Pydantic v2 — Optional fields with None default are ConfigDict(strict=True) compatible
# Confirmed by existing pattern: AgentOddsSnapshot.american_odds: Optional[int] = None

class PropParams(BaseModel):
    model_config = ConfigDict(strict=True)
    # ... existing fields ...
    last_n_games: Optional[int] = None           # e.g. 10 — filter to last N game rows
    teammate_out: Optional[list[str]] = None     # player IDs; JOIN to injury_reports
    opponent_team: Optional[str] = None          # e.g. "GSW" — filter to games vs this team
    home_away: Optional[Literal["home", "away"]] = None
```

### Pattern 4: Conditional WHERE Clause Construction (Allowlist + Positional Params)

**What:** Extend the existing filter-appending loop in `PropQueryBuilder.build()` and add analogous logic to `NBAQueryBuilder.build()`. The allowlist pattern is already established in `PROP_ALLOWED_FILTER_KEYS`.

**Security invariant preserved:** Column names come ONLY from the extended allowlist frozenset. User-supplied values (opponent name, home_away string) always go into positional args, never into the SQL string.

**Example for NBA game-log query:**
```python
# Source: Extension of existing prop/query_builder.py pattern (verified in codebase)
# Base template queries nba_player_gamelogs instead of nba_player_stats

_NBA_GAMELOG_SINGLE_TEMPLATE = """\
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN {col} >= $3 THEN 1 ELSE 0 END) AS successes,
    AVG({col}::float) AS mean_val
FROM nba_player_gamelogs
WHERE player_id = $1
  AND season >= $2
  AND {col} IS NOT NULL
"""

# Then append conditional clauses:
# last_n_games -> subquery with ORDER BY game_date DESC LIMIT
# opponent_team -> AND opponent_team = $N
# home_away -> AND is_home = $N (True/False)
# teammate_out -> AND game_id IN (SELECT DISTINCT game_id FROM injury_reports WHERE player_id = $N AND status = 'Out')
```

### Pattern 5: Graceful Wilson CI for Small Conditional Samples

**What:** Remove the hard `MIN_SAMPLE_SIZE=30` gate specifically for conditional queries. Use Wilson CI normally — it returns valid (wide) intervals for `nobs >= 2`, and `NaN` only for `nobs = 0`. Guard for the `nobs = 0` case separately.

**Verified behavior (tested against statsmodels 0.14.x in project's site-packages):**
- `nobs=0`: returns `(nan, nan)` — requires explicit `math.isnan()` guard -> return `insufficient_sample`
- `nobs=1`: returns `(0.207, 1.0)` for count=1 or `(0.0, 0.794)` for count=0 — valid, very wide
- `nobs=5`: returns CI width ~0.65 — valid, wide, correctly reflects uncertainty
- No exceptions raised for any `nobs >= 1`

**Example:**
```python
# Source: empirical test against statsmodels 0.14.x in project site-packages
import math
from statsmodels.stats.proportion import proportion_confint

# In run_prop_query (conditional path):
if total == 0:
    return PropResult(data_source="insufficient_sample", sample_size=0)

lo, hi = proportion_confint(count=successes, nobs=total, alpha=0.05, method="wilson")

if math.isnan(lo) or math.isnan(hi):
    # nobs=1 edge case safety net (should not occur given total==0 guard above)
    return PropResult(data_source="insufficient_sample", sample_size=total)

# Tag small conditional samples with wider CI and distinct data_source
data_src = "conditional_small_sample" if (is_conditional and total < 30) else "postgresql"
```

### Anti-Patterns to Avoid

- **f-string SQL for user data:** Never `f"AND opponent_team = '{params.opponent_team}'"` — always `AND opponent_team = $N` with value in args.
- **Column names from PropParams fields:** Never `f"AND {params.home_away} = ..."` — column names come from the static allowlist only.
- **Hard MIN_SAMPLE_SIZE fail on conditional queries:** Returning `insufficient_sample` for 5 conditional games destroys the feature value; use wide CI instead.
- **Float assigned to Decimal:** All CI bounds must use `Decimal(str(round(x, 6)))` — `PropResult.model_config = strict=True` rejects raw float.
- **PlayerGameLog singular for bulk ingest:** One HTTP call per player per season would be 500+ calls; use `PlayerGameLogs` (plural, bulk endpoint).
- **Last-N-games with OFFSET:** Use `ORDER BY game_date DESC LIMIT $N` as a subquery, not OFFSET-based pagination.
- **teammate_out JOIN without index:** `injury_reports` has `idx_injury_player_scraped` on `(player_name, scraped_at)` — JOIN on `player_name` is supported, but `game_id` linkage requires `idx_injury_game_id`. Verify the game_id linkage design in Plan 01 — `injury_reports.game_id` is nullable (set at scrape time), so a reliable join to game-log rows requires careful handling.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NBA per-game data | Custom NBA scraper | `nba_api.PlayerGameLogs` | Official endpoint, already installed, returns all players per season in one call |
| Wilson CI widening | Custom CI formula | `statsmodels.proportion_confint(method="wilson")` | Already proven in executor.py; widens naturally for small n — just remove hard gate |
| Home/away detection | Custom schedule lookup | Parse `MATCHUP` column from `PlayerGameLogs` | `'@' in MATCHUP` is the standard nba_api convention — no extra API call needed |
| SQL injection prevention | Custom sanitizer | Extend `PROP_ALLOWED_FILTER_KEYS` frozenset | Pattern already established, audited, and locked in the codebase |
| last_N subquery | Python-side row slicing post-query | `ORDER BY game_date DESC LIMIT $N` subquery | DB-side slicing is O(log N) with index; Python-side loads all rows |

**Key insight:** Every infrastructure piece needed for Phase 18 is already in the codebase. The work is extending existing patterns, not introducing new ones.

## Common Pitfalls

### Pitfall 1: Hard MIN_SAMPLE_SIZE Blocks All Conditional Queries
**What goes wrong:** Current `prop/executor.py` has `if total < MIN_PROP_SAMPLE_SIZE: return PropResult(data_source="insufficient_sample")`. For conditional queries (last 5 away games vs. GSW), `total` will routinely be < 30.
**Why it happens:** The `MIN_PROP_SAMPLE_SIZE=30` gate was designed for season-aggregate frequency counts, not conditional windows.
**How to avoid:** The gate must be conditional on whether the query IS a situational query. Two options: (a) remove the hard gate and always allow Wilson CI (let wide CI signal the uncertainty), or (b) add a flag `is_conditional: bool` and bypass the gate when True. Option (a) is simpler and the CI does the statistical heavy lifting.
**Warning signs:** Test returns `data_source="insufficient_sample"` for valid conditional queries with small windows.

### Pitfall 2: NaN from Wilson CI when nobs=0
**What goes wrong:** `proportion_confint(count=0, nobs=0, method="wilson")` returns `(nan, nan)`. Wrapping `nan` in `Decimal(str(round(float(nan), 6)))` produces `Decimal("nan")` which passes strict Pydantic validation but breaks downstream Kelly math.
**Why it happens:** Zero-row conditional query (no historical games matching all filters).
**How to avoid:** Guard `if total == 0: return PropResult(data_source="insufficient_sample", sample_size=0)` BEFORE calling `proportion_confint`. Separately guard with `math.isnan(lo)` as a belt-and-suspenders check.
**Warning signs:** `PropResult.true_probability` is `Decimal("nan")` in Kelly calculation.

### Pitfall 3: MATCHUP Parsing Errors for `PlayerGameLogs`
**What goes wrong:** `MATCHUP` values like `"LAL vs. BOS"` are parsed incorrectly if split on `" vs. "` fails (extra spaces, different casing).
**Why it happens:** NBA.com API occasionally has formatting inconsistencies.
**How to avoid:** Use `"@" not in matchup` for the `is_home` boolean — this is robust to spacing; split on `r" @ | vs\. "` regex for opponent extraction with a `.strip()` guard.
**Warning signs:** `opponent_team` column has `None` values or includes extra whitespace.

### Pitfall 4: `teammate_out` JOIN to `injury_reports` Requires game_id Linkage
**What goes wrong:** `injury_reports.game_id` is nullable — injury reports may arrive before `game_id` is known (per Phase 4 design). A JOIN `WHERE injury_reports.game_id = nba_player_gamelogs.game_id AND player_name = $N AND status = 'Out'` will miss reports with `game_id=NULL`.
**Why it happens:** Phase 4 intentionally allowed nullable `game_id` in `injury_reports` for pre-game reports.
**How to avoid:** Two-step approach in the executor: (1) look up `game_id` candidates from `nba_player_gamelogs` for the target player, (2) JOIN `injury_reports` on BOTH `game_id` AND `(player_name, scraped_at)` with a time window guard. OR: simplify v1 to only support `teammate_out` by filtering `nba_player_gamelogs` WHERE those games match `injury_reports` rows scraped within 24h of the `game_date`. Mark this as a known approximation in Plan 01.
**Warning signs:** `teammate_out` filter returns same results as no filter.

### Pitfall 5: `last_n_games` + Other Filters Ordering
**What goes wrong:** Applying `opponent_team` filter AFTER `last_n_games` gives "last N games overall, then filter" rather than "last N games matching this opponent."
**Why it happens:** Order of WHERE clause application matters for `LIMIT` subqueries.
**How to avoid:** Decide clearly which interpretation is correct for the use case:
- "last N games vs. opponent X" = filter by opponent first, then take last N = `WHERE opponent_team = $N ORDER BY game_date DESC LIMIT $last_n`
- "last N games, was opponent X in them" = take last N first, then filter = subquery pattern
The product intent (conditional context for upcoming game) wants the first interpretation.
**Warning signs:** Results differ from expectation for opponent-specific last-N queries.

### Pitfall 6: `player_id` type mismatch for NBA game-log table
**What goes wrong:** `nba_player_stats.player_id` is `INTEGER` (not VARCHAR). `PropParams.player_id` is `str`. The existing `NBAQueryBuilder.build()` already casts `int(params.player_id)` — the new `NBAGameLogQueryBuilder` (or extended `NBAQueryBuilder`) must do the same.
**Why it happens:** NBA API returns integer player IDs; PropParams uses `str` for cross-sport compat.
**How to avoid:** Cast `int(params.player_id)` in `build()` for all NBA paths. Document in module docstring.
**Warning signs:** `asyncpg.DataError: invalid input for query argument $1: expected int, got str`.

### Pitfall 7: NFL `player_stats` Missing `opponent_team` and `game_id` Columns
**What goes wrong:** The NFL `player_stats` table was created in Phase 1 with a column whitelist that excluded `opponent_team` and `game_id`. The nflreadpy weekly stats DO provide `opponent_team` in the raw data, but the ORM and migration don't store it.
**Why it happens:** Phase 1 whitelisted only the columns needed for Phase 11 quant engine.
**How to avoid:** Migration 0005 must add `opponent_team` (String(3), nullable) and optionally `game_id` (String(20), nullable FK) to `player_stats`. The ingestion script in `player_stats.py` must also add these to `PLAYER_STATS_COLUMNS` and `_COLUMN_RENAMES`. This is a BREAKING SCHEMA CHANGE for existing `player_stats` rows — plan must acknowledge that existing rows will have NULL in new columns.
**Warning signs:** `column "opponent_team" does not exist` error during query construction.

## Code Examples

Verified patterns from official sources / codebase inspection:

### NBA PlayerGameLogs Bulk Ingest Pattern
```python
# Source: nba_api site-packages/nba_api/stats/endpoints/playergamelogs.py (verified)
from nba_api.stats.endpoints import PlayerGameLogs
import time

def ingest_nba_gamelogs_season(season: int, engine) -> None:
    season_str = f"{season}-{str(season + 1)[-2:]}"  # e.g. 2023 -> "2023-24"
    logs = PlayerGameLogs(
        season_nullable=season_str,
        season_type_nullable="Regular Season",
        timeout=30,
    )
    time.sleep(1)  # mandatory rate limit

    df = logs.get_data_frames()[0]
    # Derive situational columns from MATCHUP
    df["is_home"] = ~df["MATCHUP"].str.contains("@")
    df["opponent_team"] = df["MATCHUP"].str.split(r" @ | vs\. ", regex=True).str[-1].str.strip()
    df["season"] = season
    # Rename, whitelist, write to nba_player_gamelogs
```

### NBA GameLog SQL Template (Conditional)
```sql
-- Source: Extension of NBAQueryBuilder pattern (codebase prop/nba_query_builder.py)
-- $1=player_id (int), $2=season (int), $3=line (float), further $N appended dynamically
-- Column name {col} substituted from NBA_GAMELOG_COLUMN_MAP allowlist — never user input
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN {col} >= $3 THEN 1 ELSE 0 END) AS successes,
    AVG({col}::float) AS mean_val
FROM nba_player_gamelogs
WHERE player_id = $1
  AND season >= $2
  AND {col} IS NOT NULL
-- Conditional clauses appended dynamically by builder:
-- AND opponent_team = $4           (if params.opponent_team)
-- AND is_home = $5                 (if params.home_away == "home" -> True, "away" -> False)
-- AND game_id IN (last_n subquery)  (if params.last_n_games)
```

### last_n_games Subquery Pattern
```sql
-- Source: Standard SQL pattern for most-recent N rows
-- This becomes a subquery wrapping the main WHERE clause
SELECT ... FROM nba_player_gamelogs
WHERE player_id = $1
  AND season >= $2
  AND {col} IS NOT NULL
  AND game_id IN (
      SELECT game_id FROM nba_player_gamelogs
      WHERE player_id = $1 AND season >= $2
      ORDER BY game_date DESC
      LIMIT $N
  )
-- Note: The LIMIT subquery must also apply any other active filters to get
-- "last N games matching THIS context" semantics
```

### Wilson CI Graceful Widening (prop/executor.py modification)
```python
# Source: Tested against statsmodels 0.14.x in project site-packages
import math
from statsmodels.stats.proportion import proportion_confint

async def run_prop_query(pool, params: PropParams) -> PropResult:
    # ... existing code ...
    total = int(row["total"]) if row and row["total"] is not None else 0
    successes = int(row["successes"]) if row and row["successes"] is not None else 0

    is_conditional = bool(
        params.last_n_games or params.teammate_out
        or params.opponent_team or params.home_away
    )

    # Guard zero — Wilson CI returns nan for nobs=0
    if total == 0:
        return PropResult(data_source="insufficient_sample", sample_size=0)

    # Remove hard MIN_SAMPLE_SIZE gate for conditional queries;
    # keep it for unconditional to preserve existing behavior
    if not is_conditional and total < MIN_PROP_SAMPLE_SIZE:
        return PropResult(data_source="insufficient_sample", sample_size=total)

    lo, hi = proportion_confint(count=successes, nobs=total, alpha=0.05, method="wilson")

    # Belt-and-suspenders NaN guard (nobs=1 edge case)
    if math.isnan(lo) or math.isnan(hi):
        return PropResult(data_source="insufficient_sample", sample_size=total)

    true_prob = Decimal(str(round(successes / total, 6)))
    ci = (Decimal(str(round(lo, 6))), Decimal(str(round(hi, 6))))
    data_src = "conditional_small_sample" if (is_conditional and total < 30) else "postgresql"

    return PropResult(
        true_probability=true_prob,
        sample_size=total,
        confidence_interval=ci,
        data_source=data_src,
        mean_stat=...,
    )
```

### PropParams Extension
```python
# Source: Pydantic v2 — Optional fields with None defaults are accepted by strict=True
# Verified by existing pattern in codebase: Optional[int] = None works in strict models
from typing import Optional, Literal

class PropParams(BaseModel):
    model_config = ConfigDict(strict=True)
    # ... all existing fields unchanged ...
    # New optional situational filters (all None by default — backward compatible)
    last_n_games: Optional[int] = None
    teammate_out: Optional[list[str]] = None
    opponent_team: Optional[str] = None
    home_away: Optional[Literal["home", "away"]] = None
```

### GraphState Extension
```python
# Source: Existing GraphState pattern (state.py) — add as last field
# Per locked decision: fields added as last entry in TypedDict definition
situational_params: dict[str, Any] | None  # injected by ContextAgent after news parsing
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Season-aggregate NBA (NormalDist CDF) | Per-game log Wilson CI for conditional queries | Phase 18 | Game-log binary frequency is statistically superior to NormalDist on aggregates for conditional inference |
| Hard 30-game gate blocks conditional queries | Graceful Wilson CI widening for n >= 1 | Phase 18 | Enables situational queries with small samples; CI width communicates uncertainty |
| PropParams has no situational context | Optional `last_n_games`, `teammate_out`, `opponent_team`, `home_away` | Phase 18 | ContextAgent can inject news-derived context into prop queries |

**Deprecated/outdated:**
- `NormalDist CDF` for NBA: still valid for unconditional season-aggregate queries, but game-log conditional queries MUST use Wilson CI frequency counting (game-by-game binary outcomes are available in `nba_player_gamelogs`).

## Open Questions

1. **NFL `player_stats` game_id and opponent_team columns: Option A vs B**
   - What we know: nflreadpy `load_player_stats()` provides `opponent_team` in raw data but it's not in the current ORM/migration
   - What's unclear: Whether adding columns to `player_stats` (Option A: schema change) or building a JOIN query on `games` table (Option B: SQL complexity) is the correct tradeoff
   - Recommendation: Plan 01 should decide. Option A (add columns to `player_stats`) is the clean path if re-ingestion is acceptable. Option B (JOIN games) avoids schema changes but requires a more complex `PropQueryBuilder` template for NFL conditional queries.

2. **`teammate_out` injury join reliability**
   - What we know: `injury_reports.game_id` is nullable; the join to game-log rows requires matching a game_id from the gamelog to an injury report from the same date
   - What's unclear: Whether `injury_reports` scraping is granular enough per-game_id to make this join reliable in practice
   - Recommendation: V1 implementation should use a date-window approximation: `JOIN injury_reports ON (player_name = $N AND status = 'Out' AND scraped_at BETWEEN game_date - INTERVAL '2 days' AND game_date + INTERVAL '1 day')`. Document as approximation.

3. **NBA game-log `game_id` format vs. `injury_reports.game_id` format**
   - What we know: `PlayerGameLogs.GAME_ID` is NBA's internal game ID (e.g., `"0022300001"`); `injury_reports.game_id` is the nflverse format (e.g., `"2025_01_KC_LAC"`)
   - What's unclear: Whether the NBA `game_id` from `PlayerGameLogs` will ever match the `game_id` in `injury_reports` (which was designed for NFL)
   - Recommendation: Do NOT join NBA gamelogs to `injury_reports` via `game_id`. Use the date-window approximation for `teammate_out` filtering on NBA as described in question 2.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2 with pytest-asyncio 0.23 |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_situational_prop_params.py tests/test_situational_query_builders.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| SC-1 | `nba_player_gamelogs` table exists; ingest populates per-game records | unit (mock nba_api) + DB | `pytest tests/test_nba_gamelogs_ingest.py -x` | Wave 0 |
| SC-2 | NBA/NFL schemas join performance to injury list by `game_id` | unit (SQL template check) | `pytest tests/test_situational_query_builders.py::test_teammate_out_join_clause -x` | Wave 0 |
| SC-3 | `PropParams` accepts situational filters; `GraphState` allows injection | unit (Pydantic validation) | `pytest tests/test_situational_prop_params.py -x` | Wave 0 |
| SC-4 | QueryBuilders produce correct conditional WHERE clauses with `$N` params only | unit | `pytest tests/test_situational_query_builders.py -x` | Wave 0 |
| SC-5 | Wilson CI widens for small samples; no hard fail on conditional queries | unit (statsmodels) | `pytest tests/test_situational_prop_params.py::test_wilson_ci_small_sample -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_situational_prop_params.py tests/test_situational_query_builders.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_nba_gamelogs_ingest.py` — covers SC-1 (ingest pipeline unit tests with mock `PlayerGameLogs`)
- [ ] `tests/test_situational_prop_params.py` — covers SC-3 (Pydantic validation of new optional fields) and SC-5 (Wilson CI small-sample behavior)
- [ ] `tests/test_situational_query_builders.py` — covers SC-2 (injury join SQL template) and SC-4 (conditional WHERE construction, positional params only, no f-string user data)

Existing test infrastructure (pytest + pytest-asyncio + conftest.py fixtures) is sufficient — no new framework installs needed.

## Sources

### Primary (HIGH confidence)
- `site-packages/nba_api/stats/endpoints/playergamelog.py` — `PlayerGameLog` columns verified from source
- `site-packages/nba_api/stats/endpoints/playergamelogs.py` — `PlayerGameLogs` columns and bulk pattern verified from source
- `site-packages/nba_api/stats/library/parameters.py` — `Location.home = "Home"`, `Location.road = "Road"` verified
- `site-packages/nflreadpy/load_stats.py` — confirmed `opponent_team` is in nflreadr data dictionary
- `src/sportsbet/prop/executor.py` — Wilson CI usage, `MIN_PROP_SAMPLE_SIZE=30` gate confirmed
- `src/sportsbet/prop/nba_executor.py` — NormalDist CDF path, `MIN_SAMPLE_GAMES=20` gate confirmed
- `src/sportsbet/graph/models.py` — `PropParams` structure, `ConfigDict(strict=True)`, `Optional[int] = None` pattern confirmed
- `src/sportsbet/graph/state.py` — `GraphState` fields, `prop_filters` pattern confirmed
- `src/sportsbet/prop/query_builder.py` — `PROP_ALLOWED_FILTER_KEYS` allowlist pattern confirmed
- `src/sportsbet/prop/nba_query_builder.py` — `NBAQueryBuilder.build()`, `int(params.player_id)` cast confirmed
- Empirical `statsmodels.stats.proportion.proportion_confint` tests against `site-packages/statsmodels` — NaN behavior for nobs=0, valid wide CI for nobs>=1

### Secondary (MEDIUM confidence)
- nflreadr data dictionary (https://nflreadr.nflverse.com/articles/dictionary_player_stats.html) — `opponent_team` confirmed in weekly player stats; no native `home_away` column (must derive from `games` schedule)
- nba_api GitHub docs (https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/playergamelog.md) — `MATCHUP` column confirmed; `@` = away, `vs.` = home encoding confirmed

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and verified in site-packages
- Architecture: HIGH — all patterns are verified extensions of existing codebase patterns
- Pitfalls: HIGH — verified against actual source code and empirical testing
- Wilson CI behavior: HIGH — empirically tested against statsmodels in project's site-packages
- NFL `player_stats` schema gap (no `opponent_team`): HIGH — verified by reading ORM model

**Research date:** 2026-03-24
**Valid until:** 2026-06-24 (90 days — stable libraries)
