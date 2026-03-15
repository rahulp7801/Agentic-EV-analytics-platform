# Phase 6: Kinematic Agent - Research

**Researched:** 2026-03-15
**Domain:** NGS tracking data queries, geometric matchup signal generation, season-availability guards, LangGraph closure-factory agent pattern
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| KINE-01 | Kinematic Agent queries NGS tracking data fields (separation at catch point, time-to-throw, press-man coverage rate) from PostgreSQL for matchup-level geometric analysis | `ngs_stats` table exists from Phase 1 with `avg_separation`, `avg_time_to_throw`, `press_man_rate` (nullable). `defense_man_zone_type` available via participation data (play-level, not player-level) |
| KINE-02 | Kinematic Agent produces matchup exploit signals based on geometric mismatches (e.g., fast slot WR vs high press-man CB) independent of box score history | KinematicAnalysis Pydantic model needed. Signal logic: compare receiver avg_separation vs historical coverage type rates. Independent of QuantResult (no true_probability). Wired as separate LangGraph node via closure factory |
| KINE-03 | System validates NGS field availability by season before Kinematic Agent queries to handle partial coverage years gracefully | NGS data available from 2016 (verified). `press_man_rate` is NULL in all loaded rows (not in raw NGS; approximated from participation data). Availability check must query `COUNT(*)` where `avg_separation IS NOT NULL` before building matchup query |
</phase_requirements>

---

## Summary

Phase 6 adds the Kinematic Agent, which queries the already-populated `ngs_stats` table (plus a new `participation_plays` view or table) to produce geometric matchup exploit signals independent of the Quant Agent's box score probability. The key signal insight is: compare a receiver's historical `avg_separation` against the opposing CB's historical `def_completion_pct` / `def_yards_allowed_per_tgt` (from PFR defensive advanced stats) or against their coverage-type rate (man vs zone, from participation data) to flag mismatches.

The critical discovery from live data inspection is that `press_man_rate` does NOT exist in the raw nflreadpy NGS data — the field is in the `ngs_stats` schema as nullable from Phase 1 precisely because it was flagged as an open question. The equivalent data lives in `load_participation()` as `defense_man_zone_type` (MAN_COVERAGE / ZONE_COVERAGE), which is available from 2016 but only filled for approximately 38-50% of plays (incomplete coverage, pun intended). A second source, `nflreadpy.load_pfr_advstats([season], stat_type="def")`, provides per-defender weekly stats including `def_targets`, `def_completion_pct`, `def_yards_allowed_per_tgt` from 2018 onward — this is the authoritative CB-level pressure metric.

The Kinematic Agent follows the identical closure-factory pattern established in Phases 3-5: `make_kinematic_agent(pool)` returns an async LangGraph node. It requires a new Alembic migration (0003) only if participation play-level coverage data is stored to PostgreSQL. For a v1 implementation that queries the existing `ngs_stats` table plus cached PFR data, no new migration is strictly required — the data was pre-loaded in Phase 1 and the `press_man_rate` nullable column is already present for forward-compatibility.

**Primary recommendation:** Implement KINE-01 and KINE-02 using `ngs_stats` (avg_separation, avg_time_to_throw) joined with PFR defensive stats for CB-level pressure metrics. For KINE-03, query `SELECT COUNT(*) FROM ngs_stats WHERE season = $1 AND stat_type = 'receiving' AND avg_separation IS NOT NULL` before any matchup query; return `KinematicAnalysis` with `None` for unavailable fields instead of raising.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | >=0.29 (installed) | Async hot-path queries against `ngs_stats` and `player_stats` | Same pool pattern as Phase 3 Quant Agent — no new dep |
| pydantic v2 | >=2.7 (installed) | KinematicParams, KinematicAnalysis I/O models with strict=True | Non-negotiable per CLAUDE.md; all agent I/O must be Pydantic-typed |
| nflreadpy | >=0.1.5 (installed) | `load_pfr_advstats([season], stat_type="def")` for CB defensive metrics | Already in pyproject.toml; PFR def stats verified available 2018-present |
| polars | >=1.0 (installed) | Ingest PFR defensive data (nflreadpy returns Polars) | Polars-first write path is locked project decision |
| structlog | >=24.1 (installed) | Structured logging per signal computation | Consistent with all prior phases |
| langgraph | >=0.2 (installed) | `make_kinematic_agent(pool)` closure wired as new graph node | All nodes follow LangGraph pattern |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| decimal (stdlib) | stdlib | All geometric metrics stored/returned as Decimal | Never float for any field that flows into Kelly sizing or Pydantic strict models |
| sqlalchemy 2.0 | >=2.0 (installed) | ORM model for `pfr_def_stats` if migration needed | Only if PFR data ingested to PostgreSQL |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PFR def stats for CB pressure rate | Participation data `defense_man_zone_type` | Participation is play-level (~40% filled); PFR is player-weekly aggregate with 100% fill from 2018. PFR is better for matchup-level analysis |
| Asyncpg raw SQL for matchup query | ORM / pandas | Asyncpg is consistent with Quant Agent; no ORM overhead in hot path |
| Per-player separation percentile | Raw avg_separation value | Percentile requires full distribution scan; raw value simpler for v1 mismatch flag |

**Installation:** No new dependencies required. All libraries already in `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure

```
src/sportsbet/
├── kinematic/
│   ├── __init__.py          # NEW: package marker
│   ├── models.py            # NEW: KinematicParams, KinematicAnalysis Pydantic models
│   ├── availability.py      # NEW: check_ngs_availability(pool, season) async function
│   └── matchup.py           # NEW: run_matchup_query(pool, params) async function
├── graph/
│   ├── agents.py            # EXTEND: make_kinematic_agent(pool) closure factory
│   ├── graph.py             # EXTEND: kinematic_agent node + route_from_master extension
│   └── state.py             # EXTEND: kinematic_result field (KinematicAnalysis | None)
tests/
│   └── test_kinematic.py    # NEW: unit tests for all kinematic module functions
```

### Pattern 1: Closure Factory (Matches Phases 3-5)

**What:** `make_kinematic_agent(pool)` returns an async function `kinematic_agent(state: GraphState) -> dict` that is registered as a LangGraph node.

**When to use:** Any agent that needs DB pool access at query time without re-creating the pool per invocation.

**Example:**
```python
# Source: pattern established in src/sportsbet/graph/agents.py (Phase 3)
def make_kinematic_agent(
    pool: asyncpg.Pool,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    from sportsbet.kinematic.availability import check_ngs_availability
    from sportsbet.kinematic.matchup import run_matchup_query
    from sportsbet.kinematic.models import KinematicParams

    async def kinematic_agent(state: GraphState) -> dict[str, Any]:
        session_id = state["session_id"]
        season = state["season"]
        log.info("kinematic_agent_invoked", session_id=session_id, season=season)

        available = await check_ngs_availability(pool, season)
        if not available:
            log.warning("kinematic_ngs_unavailable", season=season)
            return {"kinematic_result": None}

        try:
            params = KinematicParams(
                season=season,
                week=state["week"],
                receiver_gsis_id=...,  # extracted from state or injury_flags
                defender_gsis_id=...,
            )
            result = await run_matchup_query(pool, params)
        except Exception as exc:
            log.error("kinematic_agent_error", error=str(exc))
            return {"kinematic_result": None, "error": str(exc)}

        return {"kinematic_result": result}

    return kinematic_agent
```

### Pattern 2: Season Availability Guard (KINE-03)

**What:** Query `ngs_stats` to count non-null `avg_separation` rows for the requested season before any matchup query. Return `None` fields (not `0`, not exception) if the season has no data.

**When to use:** Every KinematicAgent invocation before the matchup query executes.

**Example:**
```python
# Source: adapted from NGS_MIN_SEASON guard in src/sportsbet/ingestion/ngs.py
async def check_ngs_availability(pool: asyncpg.Pool, season: int) -> bool:
    """Return True if ngs_stats has receiving rows for the given season."""
    sql = """
        SELECT COUNT(*) AS n
        FROM ngs_stats
        WHERE season = $1
          AND stat_type = 'receiving'
          AND avg_separation IS NOT NULL
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, season)
    return int(row["n"]) > 0
```

### Pattern 3: Two-Stage Pydantic Gate (Matches Phase 3 QueryBuilder)

**What:** `KinematicParams` is validated by Pydantic before any SQL executes. All column names come from an allowlist — never from `KinematicParams` fields.

**Example:**
```python
# Source: pattern from src/sportsbet/quant/query_builder.py
ALLOWED_KINEMATIC_FILTER_KEYS: frozenset[str] = frozenset({
    "season", "week", "player_gsis_id", "team_abbr", "player_position"
})

class KinematicParams(BaseModel):
    model_config = ConfigDict(strict=True)
    season: Annotated[int, Field(ge=2016, le=2030)]  # NGS available from 2016
    week: Annotated[int, Field(ge=1, le=22)]
    receiver_gsis_id: str
    min_targets: Annotated[int, Field(ge=1, le=200)] = 10
```

### Pattern 4: KinematicAnalysis Output Model

**What:** Standalone Pydantic model returned by the KinematicAgent. All fields Optional/None — not all seasons have all fields populated. Signal is independent of QuantResult.

**Example:**
```python
class KinematicAnalysis(BaseModel):
    model_config = ConfigDict(strict=True)

    season: int
    week: int
    receiver_gsis_id: str
    avg_separation: Optional[Decimal] = None        # from ngs_stats receiving
    avg_cushion: Optional[Decimal] = None           # from ngs_stats receiving
    avg_time_to_throw: Optional[Decimal] = None     # from ngs_stats passing (QB context)
    press_man_rate: Optional[Decimal] = None        # NULL — not in raw NGS; kept for forward compat
    geometric_mismatch_flag: bool = False           # True if avg_separation >= threshold
    signal_description: Optional[str] = None        # e.g. "High-separation slot vs man coverage"
    data_source: str = "ngs_stats"
    ngs_available: bool = True
```

### Anti-Patterns to Avoid

- **Querying `press_man_rate` as a primary signal:** This column is always NULL in the current data (NGS does not provide it). Use `defense_man_zone_type` from participation data or PFR defensive stats for coverage type. The nullable column exists for future-compat only.
- **Raising on partial NGS coverage:** Seasons 2016+ always have NGS data but individual players may have NULL `avg_separation` (e.g., played < minimum snaps). Return `None` for the field, not an exception.
- **Using float for Decimal fields:** The `Decimal(str(round(value, 6)))` pattern from Phase 3 must be applied to all `avg_separation`, `avg_cushion` values read from asyncpg before assignment to `KinematicAnalysis` fields.
- **LLM-inferred geometric comparisons:** The mismatch signal must be calculated from DB values with a hardcoded numeric threshold (e.g., `avg_separation >= Decimal("2.0")`). No LLM reasoning about matchup quality.
- **Importing from `graph.py` inside `kinematic/`:** The kinematic subpackage must not import from `graph/`. Only `graph/agents.py` imports from `kinematic/` — same isolation as `BacktestEngine` from Phase 3.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NGS data loading | Custom HTTP parser for NGS endpoints | `nflreadpy.load_nextgen_stats([season], stat_type=...)` | nflreadpy handles all caching, versioning, and parquet format |
| CB defensive stats | Custom web scraper for PFR | `nflreadpy.load_pfr_advstats([season], stat_type="def")` | PFR is the authoritative source; nflreadpy wraps it cleanly |
| Async DB pool | Create pool inside agent closure | `asyncpg.Pool` injected via `make_kinematic_agent(pool)` | Same pool used by Quant Agent; no new connection overhead |
| Press/man rate | Derive from play_by_play custom logic | `nflreadpy.load_participation([season])` `defense_man_zone_type` column | Participation data is the NGS-sourced coverage classifier |

**Key insight:** The `press_man_rate` field in KINE-01 requirements maps to two sources that must be queried differently. For receiver-level (WR stats), use `avg_separation` + `avg_cushion` from `ngs_stats` receiving. For CB-level coverage-type rate, compute from `nflreadpy.load_pfr_advstats(stat_type="def")` — specifically the ratio of targets where coverage was man vs zone (not directly in PFR but derivable). For v1, the mismatch flag is binary: high `avg_separation` WR against a team with high `def_completion_pct` (i.e., poor CB coverage).

---

## Common Pitfalls

### Pitfall 1: press_man_rate Does Not Exist in Raw NGS Data

**What goes wrong:** Querying `ngs_stats.press_man_rate` always returns NULL — the column was provisioned as a nullable forward-compat placeholder in Phase 1. If the Kinematic Agent relies on this field, no signal is ever produced.

**Why it happens:** CLAUDE.md and REQUIREMENTS.md reference "press-man coverage rate" as a desired signal. The actual NGS data from nflreadpy does not include this metric. The field exists at the play level in `load_participation()` as `defense_man_zone_type` only.

**How to avoid:** Use `avg_separation` (receiver NGS) + `avg_cushion` (receiver NGS) as the primary geometric mismatch inputs. Reference `defense_man_zone_type` from participation data or PFR defensive stats for coverage type. Document that `press_man_rate` in `ngs_stats` is reserved for future enrichment.

**Warning signs:** Signal descriptions referencing `press_man_rate` with non-None values should be treated as a bug in testing.

### Pitfall 2: Season Range is 2016-2025, Not 1999+

**What goes wrong:** QuantParams uses `Field(ge=1999, le=2030)`. KinematicParams must use `Field(ge=2016, le=2030)` — using the same QuantParams season range will allow 1999-2015 requests that return zero rows, failing KINE-03.

**Why it happens:** The NGS data boundary (enforced in `ingestion/ngs.py` as `NGS_MIN_SEASON = 2016`) does not propagate automatically to the Pydantic validation layer.

**How to avoid:** Define `KinematicParams.season` with `Field(ge=2016, le=2030)` explicitly. The season guard in `check_ngs_availability()` is a DB-level fallback, but the Pydantic constraint is the primary gate.

**Warning signs:** Test with `season=2015` — should raise `ValidationError`, not return empty results.

### Pitfall 3: Decimal Wrapping for asyncpg Numeric Columns

**What goes wrong:** asyncpg returns `Decimal` natively for `NUMERIC` columns, but the value may be `None` for players with insufficient snap counts. Assigning `None` to `Optional[Decimal]` in strict Pydantic is fine — but assigning a raw `Decimal` returned by asyncpg without wrapping can occasionally cause precision issues.

**Why it happens:** PostgreSQL NUMERIC(5,2) returns a Python `Decimal` from asyncpg. The `KinematicAnalysis` model uses `strict=True`. Assigning `asyncpg_decimal_value` directly is safe here (unlike statsmodels float), but `None`-handling must be explicit.

**How to avoid:** Always use explicit None checks: `Decimal(str(row["avg_separation"])) if row["avg_separation"] is not None else None`.

**Warning signs:** `ValidationError` on `KinematicAnalysis` construction complaining about field type mismatch.

### Pitfall 4: GraphState Extension Requires New field + Reducer

**What goes wrong:** Adding `kinematic_result` to `GraphState` without the correct typing causes LangGraph reducer errors on concurrent writes or state merges.

**Why it happens:** LangGraph merges partial state dicts from node returns. A new field not declared in `GraphState` is silently dropped. Fields written by multiple nodes need `Annotated` reducers.

**How to avoid:** Add `kinematic_result: Optional[KinematicAnalysis]` (with `TYPE_CHECKING`-safe import or inline annotation) to `GraphState` before wiring the kinematic node. Import `KinematicAnalysis` at runtime (not under `TYPE_CHECKING`) matching the Phase 4 decision for `ContextSignals`.

**Warning signs:** `kinematic_result` not appearing in `graph.ainvoke()` output state even after the node runs successfully.

### Pitfall 5: PFR Defensive Stats Available from 2018, Not 2016

**What goes wrong:** `nflreadpy.load_pfr_advstats([2016], stat_type="def")` raises an error — PFR advanced stats are only available from 2018. If a 2016 or 2017 season is queried with PFR dep stats, the agent crashes.

**Why it happens:** PFR defensive advanced stats have a different data availability boundary than NGS stats.

**How to avoid:** In `check_ngs_availability()` or a separate `check_pfr_availability()`, enforce `season >= 2018` before any PFR defensive query. Return `KinematicAnalysis(ngs_available=True, press_man_rate=None, signal_description="PFR def stats unavailable for seasons before 2018")` for 2016-2017.

**Warning signs:** `ValueError: Season must be between 2018 and 2025` raised inside `run_matchup_query`.

### Pitfall 6: Participation Coverage Data is ~40% Filled

**What goes wrong:** Aggregating `defense_man_zone_type` from `load_participation()` to compute a team-level man-coverage rate using a naive `COUNT(MAN_COVERAGE) / COUNT(*)` produces a misleadingly low denominator — 60% of plays have empty/null coverage type.

**Why it happens:** NGS doesn't classify every play. The `defense_man_zone_type` field is populated only for certain play types and coverage alignments.

**How to avoid:** Filter to `WHERE defense_man_zone_type IN ('MAN_COVERAGE', 'ZONE_COVERAGE')` before computing the rate. Denominator should be `COUNT(*)` over non-empty values only.

**Warning signs:** Man-coverage rate returning ~0.15-0.20 for teams expected to be heavy man-coverage teams.

---

## Code Examples

Verified patterns from existing source:

### NGS Availability Query (KINE-03)

```python
# Source: pattern from src/sportsbet/quant/executor.py (asyncpg pool.acquire pattern)
async def check_ngs_availability(pool: asyncpg.Pool, season: int) -> bool:
    """Return True if ngs_stats has receiving rows with avg_separation for the season."""
    sql = """
        SELECT COUNT(*) AS n
        FROM ngs_stats
        WHERE season = $1
          AND stat_type = 'receiving'
          AND avg_separation IS NOT NULL
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, season)
    return int(row["n"]) > 0
```

### NGS Matchup Query (KINE-01)

```python
# Source: adapted from src/sportsbet/quant/executor.py
_SEPARATION_QUERY = """
    SELECT
        player_gsis_id,
        season,
        AVG(avg_separation) AS season_avg_separation,
        AVG(avg_cushion)    AS season_avg_cushion,
        COUNT(*)            AS weeks_sampled
    FROM ngs_stats
    WHERE player_gsis_id = $1
      AND season = $2
      AND stat_type = 'receiving'
      AND avg_separation IS NOT NULL
    GROUP BY player_gsis_id, season
"""
# Usage: await conn.fetchrow(_SEPARATION_QUERY, receiver_gsis_id, season)
```

### Decimal Wrapping for asyncpg NUMERIC (Pitfall 3)

```python
# Source: pattern from src/sportsbet/quant/executor.py line 98
# asyncpg returns Decimal for NUMERIC columns — wrap in str() for precision safety
avg_sep = (
    Decimal(str(row["season_avg_separation"]))
    if row["season_avg_separation"] is not None
    else None
)
```

### GraphState Extension (Pitfall 4)

```python
# Source: pattern from src/sportsbet/graph/state.py
# Import at runtime, not TYPE_CHECKING — same as ContextSignals (Phase 4 decision)
from sportsbet.kinematic.models import KinematicAnalysis

class GraphState(TypedDict):
    # ... existing fields ...
    kinematic_result: Optional[KinematicAnalysis]
```

### route_from_master Extension (KINE wiring)

```python
# Source: src/sportsbet/graph/router.py pattern
# Add "kinematic_analysis" as a recognized request_type
def route_from_master(state: GraphState) -> str:
    if state.get("error"):
        return "end"
    rt = state.get("request_type", "")
    if rt == "kinematic_analysis":
        return "kinematic_agent"
    # ... existing routes ...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| nfl_data_py for NGS | nflreadpy (drop-in replacement) | Sep 2025 (nfl_data_py archived) | Already migrated — all ingestion uses `import nflreadpy as nfl` |
| press_man_rate from NGS | Not in NGS; use participation `defense_man_zone_type` or PFR def | Phase 1 open question resolved | Field is NULL in ngs_stats; source data identified |
| PBP-only analysis | NGS receiving (separation/cushion) + PFR defensive (targets allowed, yards/tgt) | Phase 6 introduces | Geometric matchup layer independent of box scores |

**Deprecated/outdated:**
- `nfl_data_py`: Archived Sep 2025 — project decision locks all ingestion to `import nflreadpy as nfl`. Zero `import nfl_data_py` in any `src/` file.
- Raw `press_man_rate` in ngs_stats: NULL in all current rows. Do not treat as a queryable signal without explicit ingestion from participation data.

---

## Open Questions

1. **Should participation play-level coverage data be persisted to PostgreSQL?**
   - What we know: `nflreadpy.load_participation([season])` returns 46k-48k rows per season with `defense_man_zone_type` at play level. Currently not ingested to any table.
   - What's unclear: Whether Phase 6 needs a new Alembic migration (0003) with a `participation_plays` table, or whether on-demand loading at query time via nflreadpy is acceptable for v1.
   - Recommendation: For v1 with local dev, load on demand with `load_participation()` inside the kinematic executor and compute the team-level rate in-memory. No new migration unless query performance requires it. Planner can decide.

2. **What is the mismatch threshold for `geometric_mismatch_flag`?**
   - What we know: `avg_separation` in NGS ranges roughly 1.0-4.5 yards. Elite separation is approximately >= 2.5 yards. Average CB `def_yards_allowed_per_tgt` (PFR) is ~6.5 yards/target.
   - What's unclear: The specific numeric thresholds that constitute a statistically meaningful "mismatch" require calibration against historical outcome data.
   - Recommendation: For v1, use hardcoded thresholds documented as configurable in settings (e.g., `Settings.kinematic_separation_threshold: Decimal = Decimal("2.5")`). The planner should decide whether threshold calibration is in scope for Phase 6 or deferred.

3. **KinematicAgent graph position: parallel or sequential with Quant/Arbitrage?**
   - What we know: KINE-02 explicitly states the signal must be "independent of box score history" and independent of the Quant Agent's QuantResult. The signal does not feed into Kelly sizing or the Arbitrage pipeline in v1.
   - What's unclear: Whether `kinematic_analysis` is a separate request_type dispatched by the Master Router directly, or whether it runs in parallel as a sub-node in the existing arbitrage pipeline.
   - Recommendation: Implement as a separate `request_type="kinematic_analysis"` routed by `route_from_master` directly to `kinematic_agent -> END`. This is the simplest wiring and cleanest separation of concerns. The planner should confirm.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2 with pytest-asyncio |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `python -m pytest tests/test_kinematic.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| KINE-01 | KinematicAgent query returns `avg_separation`, `avg_cushion`, `avg_time_to_throw` from ngs_stats | unit (mock pool) + integration (live DB) | `pytest tests/test_kinematic.py::test_matchup_query_returns_ngs_fields -x` | Wave 0 |
| KINE-02 | `geometric_mismatch_flag=True` when `avg_separation >= threshold` | unit | `pytest tests/test_kinematic.py::test_mismatch_flag_set_on_high_separation -x` | Wave 0 |
| KINE-02 | KinematicAnalysis signal is independent of QuantResult (no `true_probability` field) | unit | `pytest tests/test_kinematic.py::test_kinematic_analysis_has_no_quant_fields -x` | Wave 0 |
| KINE-03 | Season with no NGS data returns `KinematicAnalysis` with `None` fields, not exception | unit (mock pool returning count=0) | `pytest tests/test_kinematic.py::test_unavailable_season_returns_none_fields -x` | Wave 0 |
| KINE-03 | `KinematicParams(season=2015)` raises `ValidationError` | unit | `pytest tests/test_kinematic.py::test_kinematic_params_rejects_pre_ngs_season -x` | Wave 0 |
| KINE-01+02+03 | Full `make_kinematic_agent(pool)` closure returns correct partial state dict | integration (live DB) | `pytest tests/test_kinematic.py::test_make_kinematic_agent_end_to_end -x -m "not serial"` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_kinematic.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_kinematic.py` — covers KINE-01 through KINE-03 (6 test stubs)
- [ ] `src/sportsbet/kinematic/__init__.py` — package marker
- [ ] `src/sportsbet/kinematic/models.py` — KinematicParams, KinematicAnalysis
- [ ] `src/sportsbet/kinematic/availability.py` — check_ngs_availability()
- [ ] `src/sportsbet/kinematic/matchup.py` — run_matchup_query()

No new framework installs needed — pytest-asyncio already handles async tests with `asyncio_mode = "auto"`.

---

## Sources

### Primary (HIGH confidence)

- Live nflreadpy inspection — `load_nextgen_stats([2016..2025], stat_type="receiving/passing/rushing")` column schemas verified in project environment
- Live nflreadpy inspection — `load_participation([2016..2025])` `defense_man_zone_type`, `defense_coverage_type`, `time_to_throw` columns verified; coverage fill rate measured at 38-50% per season
- Live nflreadpy inspection — `load_pfr_advstats([2023], stat_type="def")` verified columns: `def_targets`, `def_completion_pct`, `def_yards_allowed_per_tgt`, availability from 2018
- `src/sportsbet/db/models.py` — NgsStats ORM model with `press_man_rate` as nullable confirmed; columns aligned with verified ingestion whitelist
- `src/sportsbet/ingestion/ngs.py` — `NGS_MIN_SEASON = 2016` guard; column whitelist per stat_type; Polars-first write path
- `src/sportsbet/graph/agents.py` — closure factory pattern (make_quant_agent, make_context_agent, make_arbitrage_agent) for Phase 6 replication
- `src/sportsbet/quant/executor.py` — asyncpg pool.acquire pattern, Decimal wrapping, MIN_SAMPLE_SIZE gate pattern

### Secondary (MEDIUM confidence)

- `nflreadr.nflverse.com/articles/dictionary_nextgen_stats.html` — NGS data dictionary (referenced in nflreadpy docstring; not fetched directly but aligned with live column inspection)
- `.planning/STATE.md` decisions — `[Phase 01-data-foundation P02]: press_man_rate nullable in ngs_stats — forward-compatible for Phase 6 per RESEARCH.md open question` confirms the forward-compat design intent

### Tertiary (LOW confidence)

- Separation threshold values (~2.5 yards = elite) — derived from general NFL analytics community conventions, not calibrated against project historical data. Treat as a starting heuristic.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified installed; nflreadpy API verified live
- Architecture: HIGH — closure factory and two-stage gate patterns are locked project conventions from Phases 3-5; directly replicable
- Data availability: HIGH — NGS season boundaries (2016-2025) and PFR boundary (2018-2025) verified live; press_man_rate NULL status confirmed in live data
- Pitfalls: HIGH — press_man_rate NULL, Decimal wrapping, and GraphState extension pitfalls all derived from existing codebase patterns
- Mismatch thresholds: LOW — numeric values are heuristic; need calibration

**Research date:** 2026-03-15
**Valid until:** 2026-04-15 (nflreadpy data availability; stable API)
