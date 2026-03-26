# Phase 22: Tech Debt Cleanup - Research

**Researched:** 2026-03-26
**Domain:** Python 3.12 deprecations, PostgreSQL idempotency, docstring hygiene, logging gaps, docs text accuracy, CLI/pipeline wiring
**Confidence:** HIGH

## Summary

Phase 22 is a surgical cleanup of six discrete, non-blocking tech debt items identified in the v1.0 audit. None of the items require new architectural decisions — every fix has a known, well-bounded solution already visible in the existing codebase. The work splits cleanly into two plans: 22-01 covers four in-code fixes (PBP idempotency, Python 3.12 deprecation, stale docstring, missing WARNING log) and 22-02 covers one pipeline wiring task (QUANT-04 odds_snapshots-to-BacktestSignal CLI) plus one docs text update (DATA-02 requirement text).

The most complex item is QUANT-04: creating a script that queries `odds_snapshots` rows and maps them to `BacktestSignal` inputs for automated closing-line replay. All other items are single-file, single-function changes.

**Primary recommendation:** Implement each item in strict isolation — one item per task, with its own test assertion. Do not batch unrelated changes in the same file edit.

---

## Standard Stack

### Core (already installed — no new dependencies required)

| Library | Version in pyproject | Purpose | Why Used Here |
|---------|---------------------|---------|---------------|
| SQLAlchemy | `>=2.0` | ORM + `insert().on_conflict_do_nothing()` | PBP idempotency fix |
| asyncpg | `>=0.29` | async DB access for odds_snapshots query | QUANT-04 pipeline script |
| pandas | `>=2.2` | BacktestEngine DataFrame operations | Already used in backtest.py |
| structlog | `>=24.1` | `log.warning(...)` calls | PROP-04 warning log |
| pytest | `>=8.2` | All tests; `asyncio_mode = "auto"` already set | Validation |
| pytest-asyncio | `>=0.23` | async test runner | Already configured |

### No New Dependencies

All six tech debt fixes use libraries already declared in `pyproject.toml`. Zero new `pip install` steps are needed.

---

## Architecture Patterns

### Recommended Project Structure (existing — no new directories)

```
src/sportsbet/
├── ingestion/pbp.py         # Item 1: ON CONFLICT DO NOTHING fix
├── prop/agents.py           # Item 3: docstring fix + Item 4: WARNING log
├── quant/backtest.py        # QUANT-04: no changes; consumed by new script
└── quant/backtest_replay.py # QUANT-04: NEW script/CLI entry point

tests/
├── test_graph.py            # Item 2: datetime.utcnow() fix (line 200)
└── test_backtest_replay.py  # QUANT-04: new test file
```

### Pattern 1: PostgreSQL ON CONFLICT DO NOTHING via SQLAlchemy

**What:** Replace pandas `to_sql(if_exists="append")` with a SQLAlchemy Core insert that uses the `ON CONFLICT DO NOTHING` clause, exploiting the existing `UniqueConstraint("game_id", "play_id", name="uq_pbp_game_play")`.

**When to use:** Any append-only table with a unique constraint where re-runs must be idempotent.

**The existing constraint in `db/models.py`:**
```python
UniqueConstraint("game_id", "play_id", name="uq_pbp_game_play")
```
This constraint already exists. The fix is purely in `ingestion/pbp.py` — replace `df_pd.to_sql(...)` with a chunked insert loop using `postgresql_insert(...).on_conflict_do_nothing()`.

**SQLAlchemy dialect-specific API:**
```python
# Source: SQLAlchemy 2.0 PostgreSQL dialects — insert().on_conflict_do_nothing()
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = pg_insert(PlayByPlay).on_conflict_do_nothing(
    index_elements=["game_id", "play_id"]
)
```

**Chunked execution pattern (matches existing 1000-row chunksize):**
```python
CHUNK = 1000
rows = df_pd.to_dict(orient="records")
with engine.begin() as conn:
    for i in range(0, len(rows), CHUNK):
        conn.execute(
            pg_insert(PlayByPlay).on_conflict_do_nothing(
                index_elements=["game_id", "play_id"]
            ),
            rows[i : i + CHUNK],
        )
```

**Critical constraint:** `game_id` in `play_by_play` is nullable (ForeignKey to `games.game_id`, no NOT NULL). The `on_conflict_do_nothing` must use `index_elements=["game_id", "play_id"]` — but since `game_id` can be NULL, a partial index may be needed or the UniqueConstraint behavior on NULLs must be verified. PostgreSQL treats two NULL values as distinct in unique indexes, so duplicate plays with `game_id=NULL` would not be caught. However, `play_id` alone is not unique, so the compound constraint still handles the real-world case where `game_id` is populated. The plan must note this NULL edge case.

**Confidence:** HIGH — SQLAlchemy 2.0 dialect docs confirm `on_conflict_do_nothing()` API.

### Pattern 2: Python 3.12 datetime deprecation fix

**What:** Replace `datetime.utcnow()` with `datetime.now(datetime.UTC)` (Python 3.12+ canonical replacement).

**Location:** `tests/test_graph.py` line 200 only. Verified by running `pytest tests/test_graph.py tests/test_quant.py -W error::DeprecationWarning` — two tests fail, both trace to line 200.

**Fix:**
```python
# Before (deprecated since Python 3.12):
"created_at": datetime.utcnow(),

# After (correct):
"created_at": datetime.now(datetime.UTC),
```

`datetime.UTC` is available from Python 3.11+. The project requires `python >= 3.12` per `pyproject.toml`, so this is safe.

**Asyncio note:** The phase description mentions `asyncio.get_event_loop()` as a second target. Scanning the codebase reveals this was already fixed in Phase 5 decision: "asyncio.run() replaces deprecated asyncio.get_event_loop().run_until_complete() in test_quant.py". Confirmed by running `grep -rn "get_event_loop" tests/` — zero results in test files. The only remaining deprecation warning source is the `datetime.utcnow()` at line 200 of `test_graph.py`.

**Confidence:** HIGH — confirmed by live `pytest -W error::DeprecationWarning` run.

### Pattern 3: Module docstring replacement

**What:** The `src/sportsbet/prop/agents.py` module docstring currently contains "Kinematic integration is a TODO placeholder for Plan 02" — this language was accurate during Phase 11 Plan 01 but is stale now that Plan 02 completed the kinematic adjustment implementation.

**Current stale text (lines 6-8 of `prop/agents.py`):**
```
Kinematic integration is a TODO placeholder for Plan 02:
- _apply_kinematic_adjustment(result, None, prop_type) is called here as a no-op stub.
- Plan 02 passes a real KinematicAnalysis object and implements the delta/clamping logic.
```

**Replacement:** Replace with an accurate description of what the module actually does: full NFL player prop probability estimation with kinematic boost support for receiving props.

**Success criterion:** After fix, the word "TODO placeholder" must not appear in the file.

**Confidence:** HIGH — direct file inspection of `prop/agents.py` lines 1-8.

### Pattern 4: structlog WARNING on None kinematic_result for receiving props

**What:** `make_prop_quant_agent` currently silently proceeds when `kinematic_result is None` for a receiving prop request. PROP-04 specifies the two-invocation pattern where kinematic data is expected. A missing kinematic result on a receiving prop is a gap worth flagging.

**Location:** `src/sportsbet/prop/agents.py` — inside the `prop_quant_agent` inner function, after the `kinematic_result` extraction at line 182.

**Current behavior:**
```python
kinematic_result: Optional[KinematicAnalysis] = state.get("kinematic_result")
result = _apply_kinematic_adjustment(result, kinematic_result, params.prop_type)
```

**Required behavior:** Log a WARNING when `kinematic_result is None` AND `prop_type` is in `RECEIVING_PROPS`.

**Implementation pattern (consistent with existing structlog usage):**
```python
if kinematic_result is None and params.prop_type in RECEIVING_PROPS:
    log.warning(
        "prop_quant_agent_kinematic_missing",
        session_id=session_id,
        prop_type=params.prop_type,
        msg="kinematic_result is None for receiving prop — PROP-04 two-invocation pattern gap",
    )
```

**Confidence:** HIGH — direct inspection of `prop/agents.py`; structlog pattern consistent with existing `log.info(...)` and `log.error(...)` calls in same function.

### Pattern 5: QUANT-04 BacktestEngine pipeline from odds_snapshots

**What:** A new CLI script `src/sportsbet/quant/backtest_replay.py` that:
1. Queries `odds_snapshots` rows (pre-game snapshots only: `snapped_at < game_start_time`)
2. Maps each row to a `BacktestSignal` input format
3. Feeds them to `BacktestEngine.run()`
4. Prints/returns a `BacktestReport`

**Schema of `odds_snapshots` table (from `db/models.py`):**
| Column | Type | Purpose |
|--------|------|---------|
| `id` | BigInteger | PK |
| `game_id` | String(20) | FK to games |
| `sportsbook` | String(50) | e.g. "fanduel" |
| `market_type` | String(30) | e.g. "h2h" |
| `line` | Numeric(6,2) | spread/total line |
| `price` | SmallInteger | American odds |
| `snapped_at` | TIMESTAMPTZ | snapshot timestamp |

**BacktestSignal fields required (from `quant/backtest.py`):**
| Field | Type | Source |
|-------|------|--------|
| `quant_result` | `QuantResult` | Requires `true_probability` — must be sourced or stubbed |
| `closing_implied_prob` | `Decimal` | Derived from `odds_snapshots.price` via `vig.py` |
| `actual_outcome` | `bool` | Not in `odds_snapshots` — caller must provide or stub |
| `stake` | `Decimal` | Configuration parameter |
| `payout_multiplier` | `Decimal` | Derived from `odds_snapshots.price` |
| `game_start_time` | `datetime` | From `games.game_date` or a provided input |
| `snapshot_time` | `datetime` | `odds_snapshots.snapped_at` |

**Key design gap:** `BacktestSignal` requires `actual_outcome` (did the bet win?) and `quant_result.true_probability` — neither is stored in `odds_snapshots`. The script must either:
- Accept actual outcomes as a separate input (CSV or JSON file), OR
- Operate in CLV-only mode (which does not need `actual_outcome`) by computing raw CLV from closing vs opening price

The phase description says "automated closing-line replay" — the primary output metric is CLV (closing line value), not ROI/hit-rate. The script should compute closing-line implied probability from `odds_snapshots` rows and support CLV analysis. For `actual_outcome`, a `--outcomes-file` argument is most maintainable.

**Vig conversion (existing utility):**
```python
# From src/sportsbet/quant/vig.py (already exists)
# American odds -> implied probability with vig removal
from sportsbet.quant.vig import remove_vig_multiplicative
```

The American-odds-to-implied-probability conversion already exists in `vig.py` and `graph/agents.py` (`_extract_odds_snapshot`). The replay script should use the same conversion path.

**CLI entry point pattern (consistent with existing `quant/backtest.py` `__main__` block):**
```python
# python -m sportsbet.quant.backtest_replay --game-id 2024_01_KC_DET --market h2h
```

**Confidence:** MEDIUM — schema and BacktestEngine interfaces are HIGH confidence (inspected directly); the design decision on `actual_outcome` sourcing is architectural and the planner must make it explicit.

### Pattern 6: DATA-02 documentation text fix

**What:** `REQUIREMENTS.md` DATA-02 description still reads "nfl_data_py" but the project decided in Phase 1 to use `nflreadpy` (nfl_data_py archived Sep 2025). The text must be updated to "nflreadpy".

**Location:** `.planning/REQUIREMENTS.md` line 12:
```
- [x] **DATA-02**: System ingests multi-season NFL PBP data via nfl_data_py using a year-by-year loading loop with column whitelist and gc.collect() to prevent OOM
```

**Fix:** Replace "nfl_data_py" with "nflreadpy" in this single line.

**Confidence:** HIGH — direct file inspection.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PBP duplicate prevention | Custom de-dup query or application-layer duplicate check | `pg_insert(...).on_conflict_do_nothing()` | PostgreSQL handles this atomically at DB layer; application-layer is race-condition-prone |
| American odds to implied probability | New conversion function | `vig.py` + `_extract_odds_snapshot` in `graph/agents.py` | Already implemented with devig (multiplicative/power); re-use existing tested code |
| Deprecation detection | Manual codebase scan | `pytest -W error::DeprecationWarning` | Pytest surfaces all active deprecations in one command |

---

## Common Pitfalls

### Pitfall 1: NULL game_id in ON CONFLICT DO NOTHING
**What goes wrong:** PostgreSQL treats `NULL != NULL` in unique indexes. Two rows with `game_id=NULL, play_id=X` are NOT treated as duplicates by the unique constraint `uq_pbp_game_play`. If the re-run has plays with NULL `game_id`, they bypass the conflict guard and get inserted again.
**Why it happens:** PBP rows from nflreadpy may have NULL `game_id` if the FK join hasn't happened yet (the `play_by_play.game_id` is `nullable=True`).
**How to avoid:** The plan must document that `ON CONFLICT DO NOTHING` only protects rows where both `game_id` AND `play_id` are non-NULL. For NULL-game_id scenarios, the protection is partial. Accept this limitation in v1 — full idempotency for NULL-game_id rows would require a separate unique index on `play_id` alone (which conflicts with multiple seasons having the same `play_id` values).
**Warning signs:** `IntegrityError` only eliminated for rows with non-NULL `game_id`.

### Pitfall 2: datetime.UTC vs timezone.utc
**What goes wrong:** Using `datetime.UTC` (Python 3.11+) instead of `timezone.utc` (Python 3.2+) is correct and preferred, but requires no additional imports when `datetime` is imported as `from datetime import datetime`.
**Why it happens:** `datetime.UTC` is an attribute on the `datetime` module, not on `datetime.datetime`. When using `from datetime import datetime`, it must be accessed as `datetime.timezone.utc` or via `from datetime import timezone; timezone.utc`.
**How to avoid:** Use `datetime.now(timezone.utc)` with `from datetime import datetime, timezone` — this is consistent with the pattern already used in `test_graph.py` line 27 (`datetime(2026, 1, 1, tzinfo=timezone.utc)`).
**Warning signs:** `AttributeError: type object 'datetime.datetime' has no attribute 'UTC'` if `datetime` is imported from the class rather than the module.

### Pitfall 3: BacktestSignal requires QuantResult — not just a probability
**What goes wrong:** The QUANT-04 script needs `BacktestSignal.quant_result: QuantResult`, not a raw Decimal. Callers must construct a full `QuantResult` object, even if only `true_probability` is populated.
**Why it happens:** `BacktestEngine` accesses `s.quant_result.true_probability` and skips signals where it is None. A plain `Decimal` would fail type checking.
**How to avoid:** Construct `QuantResult(true_probability=Decimal(str(implied_prob)))` in the mapping layer. Note that `QuantResult` has all-nullable fields (Phase 2 decision) so a minimal constructor is valid.

### Pitfall 4: pandas to_sql method="multi" dropped — use SQLAlchemy Core
**What goes wrong:** The current `pbp.py` uses `df_pd.to_sql(method="multi")`. Once replaced with SQLAlchemy Core chunked insert, the old `to_sql` call must be completely removed — not kept as a fallback.
**Why it happens:** Having both paths would mean the idempotency fix is conditional.
**How to avoid:** The new chunked-insert block fully replaces the `df_pd.to_sql(...)` call. Keep the `df_pd = df.to_pandas()` conversion (still needed to get `.to_dict(orient="records")`), just remove the `.to_sql(...)` line.

### Pitfall 5: structlog WARNING vs Python logging WARNING
**What goes wrong:** The existing agents use `structlog.get_logger()` — `log.warning(...)` is the correct call. Do NOT use `import logging; logging.warning(...)` which bypasses structlog processors.
**Why it happens:** Python's stdlib logging is a familiar default; structlog is project convention.
**How to avoid:** All logging in `prop/agents.py` already uses `log = structlog.get_logger()`. The new WARNING call must use `log.warning(...)`.

---

## Code Examples

### ON CONFLICT DO NOTHING — SQLAlchemy 2.0 PostgreSQL dialect

```python
# Source: SQLAlchemy 2.0 PostgreSQL dialect documentation
# Replaces: df_pd.to_sql("play_by_play", engine, if_exists="append", ...)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sportsbet.db.models import PlayByPlay

CHUNK = 1000
rows = df_pd.to_dict(orient="records")
with engine.begin() as conn:
    for i in range(0, len(rows), CHUNK):
        conn.execute(
            pg_insert(PlayByPlay).on_conflict_do_nothing(
                index_elements=["game_id", "play_id"]
            ),
            rows[i : i + CHUNK],
        )
```

### datetime.utcnow() replacement — Python 3.12+

```python
# Before (deprecated, raises DeprecationWarning under -W error):
"created_at": datetime.utcnow(),

# After (correct, consistent with existing test_graph.py line 27 pattern):
from datetime import datetime, timezone
"created_at": datetime.now(timezone.utc),
```

### structlog WARNING — consistent with existing prop/agents.py pattern

```python
# Add after kinematic_result extraction, before _apply_kinematic_adjustment call:
if kinematic_result is None and params.prop_type in RECEIVING_PROPS:
    log.warning(
        "prop_quant_agent_kinematic_missing",
        session_id=session_id,
        prop_type=params.prop_type,
    )
```

### BacktestSignal construction from odds_snapshots row

```python
# Mapping pattern for QUANT-04 replay script
from decimal import Decimal
from sportsbet.quant.backtest import BacktestSignal
from sportsbet.graph.models import QuantResult

def odds_row_to_signal(
    row: dict,
    true_prob: Decimal,
    closing_prob: Decimal,
    actual_outcome: bool,
) -> BacktestSignal:
    price: int = row["price"]
    # American odds to payout multiplier: +110 -> 2.1, -110 -> 1.909
    if price > 0:
        payout = Decimal(str(round(1 + price / 100, 6)))
    else:
        payout = Decimal(str(round(1 + 100 / abs(price), 6)))
    return BacktestSignal(
        quant_result=QuantResult(true_probability=true_prob),
        closing_implied_prob=closing_prob,
        actual_outcome=actual_outcome,
        stake=Decimal("100"),
        payout_multiplier=payout,
        game_start_time=row["game_start_time"],
        snapshot_time=row["snapped_at"],
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `df_pd.to_sql(if_exists="append")` raises IntegrityError on re-run | `pg_insert(...).on_conflict_do_nothing()` silent on duplicate | Phase 22 (this fix) | Re-running PBP ingest is idempotent |
| `datetime.utcnow()` in test helper | `datetime.now(timezone.utc)` | Python 3.12 (deprecated) | Zero DeprecationWarnings under `-W error` |
| Stale "TODO placeholder" docstring in `prop/agents.py` | Accurate module description | Phase 22 (this fix) | No misleading Phase 11 stub language |
| Silent None kinematic_result for receiving props | `log.warning(...)` on missing kinematic | Phase 22 (this fix) | PROP-04 two-invocation pattern gap visible in logs |
| "nfl_data_py" text in REQUIREMENTS.md DATA-02 | "nflreadpy" | Phase 22 (this fix) | Docs match actual implementation |
| No automated path from `odds_snapshots` to `BacktestEngine` | `backtest_replay.py` CLI script | Phase 22 (this fix) | QUANT-04 fully automated |

---

## Open Questions

1. **ON CONFLICT NULL game_id edge case**
   - What we know: PostgreSQL NULL != NULL in unique indexes; `game_id` is nullable
   - What's unclear: Whether any production PBP rows have NULL `game_id` after ingest
   - Recommendation: Document the limitation; do not add a workaround index — scope creep. The fix eliminates IntegrityError for non-NULL game_id plays, which is the dominant case.

2. **QUANT-04 actual_outcome sourcing**
   - What we know: `BacktestSignal.actual_outcome: bool` is required; not stored in `odds_snapshots`
   - What's unclear: Whether the planner wants CLV-only mode (no actual_outcome needed for clv_mean) or full ROI/hit-rate support
   - Recommendation: Build the script to accept an optional `--outcomes-file` JSON argument. When not provided, construct signals with `actual_outcome=False` as a placeholder and only report `clv_mean` (not `roi` or `hit_rate`). This keeps the script runnable without external data while supporting full backtesting when outcomes are supplied.

3. **QUANT-04 game_start_time source**
   - What we know: `BacktestSignal.game_start_time` is required; `odds_snapshots.game_id` is nullable and links to `games.game_date` (not a datetime, just a date)
   - What's unclear: Whether a JOIN to `games` table or a passed `--game-start` argument is cleaner
   - Recommendation: Use a `games` table JOIN via `games.game_date` cast to `TIMESTAMPTZ` at midnight UTC as a pragmatic default. `game_date` is `Date` type in the ORM; `datetime.combine(game_date, time(18, 0, tzinfo=timezone.utc))` as a reasonable NFL kickoff default is acceptable for v1.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2 + pytest-asyncio 0.23 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_graph.py tests/test_quant.py tests/test_ingestion.py -x -q` |
| Full suite command | `pytest tests/ -q` |

### Phase Requirements → Test Map

No formal REQ-IDs are assigned to Phase 22 (the phase description states `null`). Each success criterion maps to a test assertion:

| Success Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-------------------|----------|-----------|-------------------|--------------|
| SC-1: PBP ON CONFLICT | Re-running `ingest_pbp_seasons` does not raise IntegrityError | unit (mock engine) | `pytest tests/test_ingestion.py -k "pbp" -x -q` | ✅ partial — needs new assertion |
| SC-2: Zero DeprecationWarnings | `test_graph.py` and `test_quant.py` pass under `-W error::DeprecationWarning` | unit | `pytest tests/test_graph.py tests/test_quant.py -W error::DeprecationWarning -x -q` | ✅ tests exist, fix needed |
| SC-3: No TODO placeholder | `prop/agents.py` module docstring does not contain "TODO placeholder" | doc check (grep or unit) | `pytest tests/ -k "docstring" -x -q` OR `grep -c "TODO placeholder" src/sportsbet/prop/agents.py` | ❌ Wave 0 gap |
| SC-4: WARNING log on None kinematic | `log.warning` called when `kinematic_result=None` and `prop_type in RECEIVING_PROPS` | unit (caplog) | `pytest tests/test_prop_executor.py -k "kinematic_warning" -x -q` | ❌ Wave 0 gap |
| SC-5: DATA-02 text fix | `REQUIREMENTS.md` does not contain "nfl_data_py" in DATA-02 line | doc check | `grep -c "nfl_data_py" .planning/REQUIREMENTS.md` (expect 0) | ✅ no test needed — grep check |
| SC-6: QUANT-04 backtest_replay | Script maps `odds_snapshots` rows to `BacktestSignal` and produces `BacktestReport` | unit + integration | `pytest tests/test_backtest_replay.py -x -q` | ❌ Wave 0 gap |

### Sampling Rate

- **Per task commit:** `pytest tests/test_graph.py tests/test_quant.py -W error::DeprecationWarning -x -q`
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_prop_executor.py` — add `test_kinematic_missing_warning` for SC-4 (caplog fixture checking `log.warning` on None kinematic + receiving prop)
- [ ] `tests/test_backtest_replay.py` — new file covering SC-6: mock `odds_snapshots` query → `BacktestSignal` mapping → `BacktestReport` output
- [ ] Add docstring assertion or pytest test for SC-3 (can be a simple `test_no_todo_placeholder` that imports `prop.agents` and checks `__doc__`)

---

## Sources

### Primary (HIGH confidence)

- Direct file inspection: `src/sportsbet/ingestion/pbp.py` — current `to_sql` approach
- Direct file inspection: `src/sportsbet/db/models.py` — `UniqueConstraint("game_id", "play_id")` confirmed
- Direct file inspection: `src/sportsbet/prop/agents.py` — stale docstring lines 1-8, kinematic None path lines 182-183
- Direct file inspection: `src/sportsbet/quant/backtest.py` — `BacktestSignal` and `BacktestEngine.run()` interface
- Direct file inspection: `src/sportsbet/db/models.py` — `OddsSnapshot` schema
- Direct file inspection: `.planning/REQUIREMENTS.md` line 12 — "nfl_data_py" text
- Live test run: `pytest tests/test_graph.py tests/test_quant.py -W error::DeprecationWarning` — 2 failures, both from `datetime.utcnow()` at `test_graph.py:200`
- Live grep: `grep -rn "utcnow|get_event_loop" tests/` — only one hit confirmed
- Direct file inspection: `pyproject.toml` — `asyncio_mode = "auto"`, `requires-python = ">=3.12"`

### Secondary (MEDIUM confidence)

- SQLAlchemy 2.0 PostgreSQL dialect: `insert().on_conflict_do_nothing(index_elements=[...])` — consistent with standard SQLAlchemy 2.x dialect documentation pattern
- Python 3.12 changelog: `datetime.utcnow()` deprecated; `datetime.now(timezone.utc)` is canonical replacement

### Tertiary (LOW confidence)

- None — all claims are directly verified by code inspection or live test run.

---

## Metadata

**Confidence breakdown:**

- Items 1-5 (code/doc fixes): HIGH — all located by direct file inspection with exact line numbers
- Item 6 (QUANT-04 script): MEDIUM — interface is HIGH confidence, `actual_outcome` sourcing is an architectural open question the planner must resolve
- Pitfalls: HIGH — derived from direct code inspection and live test execution
- Validation architecture: HIGH — test framework verified by `pyproject.toml` and live run

**Research date:** 2026-03-26
**Valid until:** 2026-04-25 (stable domain — no fast-moving library changes)
