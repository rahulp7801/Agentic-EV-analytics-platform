# Phase 9: Critical Pipeline Gap Closure - Research

**Researched:** 2026-03-22
**Domain:** PostgreSQL schema synchronization, staleness gating, odds CLV persistence
**Confidence:** HIGH — all three gaps are directly verified by reading the production source files; no external library research required

---

## Summary

The v1.0 milestone audit identified three production-blocking gaps that prevent the quant and arbitrage pipeline from producing any real signal. All three are surgical code-and-schema fixes with no new dependencies. No new library research is required — the entire fix surface is within files that already exist.

**GAP-1 (P0 blocker):** `query_builder.py` references `air_yards`, `two_point_attempt`, and `complete_pass` in its SQL templates, but none of these columns exist in the `play_by_play` ORM model, the Alembic `0001` migration DDL, or the `PBP_COLUMNS` ingestion whitelist. Every call to `run_quant_query` raises `column "air_yards" does not exist` in PostgreSQL, which causes `make_quant_agent` to catch the exception and return `QuantResult(data_source="error")`. Since `make_arbitrage_agent` guards on `true_probability is None`, no arbitrage signal is ever produced against a real database.

**GAP-2 (P1 blocker):** `is_stale()` is fully implemented in `sportsbet.ingestion.odds_poller` and is already tested in `test_context.py`. It is never imported or called inside `make_context_agent` in `agents.py`. Stale odds pass through unconditionally to `ContextSignals.odds_snapshot`.

**GAP-3 (P2):** `write_odds_snapshot()` is called with `OddsSnapshotCreate(price=None)` because `AgentOddsSnapshot` stores a devigged Decimal `implied_probability`, not an American odds integer. The `odds_snapshots.price` column in both the ORM and migration is typed `SmallInteger` (American odds). Every row is written with `price=NULL`. CLV comparison has no usable numeric reference.

**Primary recommendation:** Fix all three gaps in a single plan. GAP-1 requires a new Alembic migration (0003), ORM additions, whitelist expansion, and a live-DB integration test. GAP-2 is a two-line import + conditional in `make_context_agent`. GAP-3 requires deciding the storage strategy (American int vs. Decimal probability) and propagating the change consistently.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| QUANT-03 | System executes dynamic historical win-rate SQL queries parameterized by game context | GAP-1 fix: add `air_yards`, `two_point_attempt`, `complete_pass` to schema + whitelist so `run_quant_query` can reach a real DB row |
| QUANT-01 | Two-stage SQL validation gate: QuantParams → QueryBuilder → parameterized SQL, no raw LLM SQL | GAP-1 fix: the gate is already wired; execution stage fails only because of absent columns — fixing schema completes this requirement |
| CTXT-02 | Reject odds payload older than configurable staleness threshold before passing to Arbitrage Agent | GAP-2 fix: call `is_stale(odds_snapshot.snapped_at)` inside `make_context_agent` and null out the snapshot if stale |
| DATA-03 | Store timestamped odds snapshots to PostgreSQL for CLV calculation | GAP-3 fix: write a non-null numeric value (American int or Decimal probability) to the odds snapshot row |
| ARBT-01 | Arbitrage Agent flags +EV discrepancies: EV%, 3-bullet Trade Plan, fractional Kelly | Unblocked by GAP-1: once `run_quant_query` returns a real `true_probability`, the existing `make_arbitrage_agent` code is correct and produces EVSignal |
</phase_requirements>

---

## Standard Stack

No new libraries. All existing project dependencies apply.

### Core (already installed)
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| SQLAlchemy | >=2.0 | ORM models + Mapped/mapped_column DDL | `db/models.py` uses 2.x DeclarativeBase |
| Alembic | >=1.13 | Schema migration | Hand-written migrations only — autogenerate omits composite indexes |
| asyncpg | >=0.29 | Async PostgreSQL pool for quant queries | Hot path |
| Pydantic v2 | >=2.7 | `OddsSnapshotCreate`, `AgentOddsSnapshot` | `strict=True` throughout; `Decimal(str(...))` pattern required |
| nflreadpy | >=0.1.5 | PBP ingestion; `PBP_COLUMNS` whitelist controls what is loaded | Polars-first; `to_pandas()` only before `to_sql()` |

### No New Dependencies
All three fixes are localized edits to existing modules. `pip install` is not required.

---

## Architecture Patterns

### Pattern 1: Lockstep Schema-ORM-Whitelist Synchronization (GAP-1)

**What:** Any column used in a SQL template must appear in three places atomically: ORM model, Alembic migration DDL, and `PBP_COLUMNS` ingestion whitelist. Missing any one of the three causes a failure mode (column absent from DB, or absent from loaded DataFrame, or absent from ORM-based checks).

**When to use:** Every time a new `play_by_play` column is referenced in `query_builder.py`.

**The three files that must change together:**
```
src/sportsbet/db/models.py          # PlayByPlay ORM — Mapped column declaration
alembic/versions/0003_*.py          # New migration — op.add_column() for each new column
src/sportsbet/ingestion/pbp.py      # PBP_COLUMNS list — add column name string
```

**Column specifications for GAP-1:**
- `air_yards`: `SmallInteger`, nullable — nflreadpy field `air_yards` is integer (yards as whole number). Present since ~2009. Used in `_PASSING_TEMPLATE` `SUM(CASE WHEN ...)`.
- `two_point_attempt`: `SmallInteger`, nullable — binary flag (0/1). Used in all three templates as `WHERE two_point_attempt = 0`.
- `complete_pass`: `SmallInteger`, nullable — binary flag (0/1). Used in `_RECEIVING_TEMPLATE` `SUM(CASE WHEN complete_pass = 1 THEN 1 ELSE 0 END)`.

All three should be `SmallInteger` to match the existing pattern (`pass_touchdown`, `rush_touchdown`, `interception` are all `SmallInteger`).

### Pattern 2: Alembic Migration Naming (established convention)

```
alembic/versions/0003_add_pbp_quant_columns.py
```

- `revision = "0003_add_pbp_quant_columns"` (full form matches 0002 pattern)
- `down_revision = "0002_add_injury_reports"` — chains from 0002
- `upgrade()`: three `op.add_column("play_by_play", ...)` calls
- `downgrade()`: three `op.drop_column("play_by_play", ...)` calls in reverse
- No new indexes needed — existing `idx_pbp_play_type_season` and `idx_pbp_posteam_season` cover the added WHERE clauses

**CRITICAL:** The `down_revision` string must exactly match the `revision` field in `0002_add_injury_reports.py`, which is `"0002_add_injury_reports"`.

### Pattern 3: Staleness Gate Insertion (GAP-2)

**What:** After `_extract_odds_snapshot()` returns in `make_context_agent`, call `is_stale()` before proceeding. If stale, set `odds_snapshot = None`. The skip-persistence path (`if odds_snapshot is not None`) already handles the None case correctly for step 1b.

**Import location:** `is_stale` must be imported inside the closure body (same pattern as `OddsAPIPoller`, `BudgetExhaustedError`), not at module level. The closure uses deferred imports throughout.

**Staleness threshold:** `DEFAULT_STALENESS_MINUTES = 5` from `odds_poller.py`. The gate should use this default unless the caller passes an override. For Phase 9, hardcode to the default (config-driven threshold is a v2 concern).

```python
# After _extract_odds_snapshot() call, inside make_context_agent closure:
from sportsbet.ingestion.odds_poller import is_stale as _is_stale
if odds_snapshot is not None and _is_stale(odds_snapshot.snapped_at):
    log.warning("context_agent_stale_odds_rejected",
                session_id=session_id,
                snapped_at=str(odds_snapshot.snapped_at))
    odds_snapshot = None
```

**No test changes required** for the staleness unit tests in `test_context.py` — `test_staleness_guard_rejects_stale` and `test_staleness_guard_passes_fresh` already pass. A new integration test for the wiring path is required.

### Pattern 4: GAP-3 CLV Storage Decision

**The problem:** `AgentOddsSnapshot.implied_probability` is a devigged `Decimal`. `OddsSnapshot.price` is `SmallInteger` (American odds integer). The two types are incompatible. `agents.py` hardcodes `price=None` because there is no conversion in scope.

**Two valid fixes — choose one:**

**Option A (recommended): Store American odds integer in `price`**
- Raw American odds prices are already available in `_extract_odds_snapshot` as `prices[0]` (the list extracted from outcomes before devig). Store `prices[0]` as the American odds integer in `OddsSnapshotCreate.price`.
- Pros: no schema change; `OddsSnapshot.price SmallInteger` already exists and is typed for American odds.
- Cons: requires threading the raw int back through `AgentOddsSnapshot` or computing the price in the persistence block.
- Implementation: `AgentOddsSnapshot` needs an `american_odds: Optional[int]` field, populated from `prices[0]` in `_extract_odds_snapshot`. Then `OddsSnapshotCreate(price=odds_snapshot.american_odds, ...)`.

**Option B: Add `implied_probability NUMERIC(10,8)` column to `odds_snapshots`**
- Add `implied_probability: Mapped[Optional[Decimal]] = mapped_column(Numeric(10,8))` to `OddsSnapshot` ORM and a 0004 migration.
- Store `AgentOddsSnapshot.implied_probability` directly.
- Pros: precision preserved; CLV math uses Decimal directly.
- Cons: requires an additional migration and ORM change; increases phase scope.

**Recommendation: Option A** — adds `american_odds: Optional[int]` to `AgentOddsSnapshot` (one field), no schema migration needed, no new Alembic revision. Keeps price column purpose-consistent with its SmallInteger type. CLV can be computed from American odds at query time.

**If Option A is chosen**, `AgentOddsSnapshot` field addition must satisfy `ConfigDict(strict=True)` — use `Optional[int]` not `int`. The `_extract_odds_snapshot` function already has `prices[0]` in scope.

### Anti-Patterns to Avoid

- **Amending migration 0001:** Do not add columns to the initial schema migration. All existing databases have already applied 0001. A new 0003 migration is required.
- **Float in Decimal fields:** The Pydantic `strict=True` pattern throughout this codebase rejects float → Decimal coercion. Any new probability value must use `Decimal(str(round(x, 6)))`.
- **Module-level import of `is_stale` in `agents.py`:** The existing closure pattern defers all subpackage imports inside the closure body. Follow the same pattern to avoid circular imports.
- **Modifying `OddsSnapshotCreate.price` validator:** The existing `validate_american_odds` rejects `price=0`. An American odds value of `prices[0]` from a real Odds API response is never 0 (sportsbooks don't offer 0-cent lines), but the validator must be accounted for.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema migration | Manual SQL ALTER TABLE | Alembic `op.add_column` | Tracks revision chain, supports downgrade |
| Staleness check | Custom datetime arithmetic in agents | `is_stale()` already in `odds_poller.py` | Already implemented, already tested, already handles naive datetime TypeError |
| Wilson CI | Custom proportion confidence interval | `statsmodels.stats.proportion.proportion_confint` (already used) | Precision validated, no new dependency |
| Decimal/float conversion | `float(x)` assignment to Decimal field | `Decimal(str(round(x, 6)))` (project pattern) | strict=True Pydantic rejects raw float |

---

## Common Pitfalls

### Pitfall 1: Migration revision chain breaks
**What goes wrong:** `down_revision` in 0003 set to `"0002"` instead of `"0002_add_injury_reports"` — Alembic raises `Can't locate revision 0002`.
**Why it happens:** Revision IDs use the full form in this project (see 0002 header: `revision = "0002_add_injury_reports"`). Short-form `"0002"` does not match.
**How to avoid:** Always copy the `revision` value from the target migration's header exactly. Confirmed: `0002_add_injury_reports.py` has `revision = "0002_add_injury_reports"`.

### Pitfall 2: Stale odds test asserts `price is None` — test breaks if GAP-3 is fixed to write price
**What goes wrong:** `test_context_agent_persists_odds_snapshot` in `test_context.py` line 425 asserts `snap_create.price is None`. After GAP-3 fix, price will be a non-None int.
**Why it happens:** The test was written to document the broken behavior, not the desired behavior.
**How to avoid:** Update this test assertion to `assert snap_create.price is not None` and `assert isinstance(snap_create.price, int)` when GAP-3 is fixed.

### Pitfall 3: `air_yards` is SmallInteger but can be NULL or negative
**What goes wrong:** `SUM(CASE WHEN ... air_yards > 0 THEN 1 ELSE 0 END)` works correctly with NULLs (CASE returns ELSE=0 for NULL), but loading data where `air_yards` exceeds SmallInteger range (-32768 to 32767) would cause overflow.
**Why it happens:** nflreadpy `air_yards` field is typically -10 to 50+ yards. SmallInteger is sufficient. No risk in practice.
**How to avoid:** Use `SmallInteger` (consistent with all other play-level integer fields). Do not use `Integer` — that would be inconsistent and waste storage.

### Pitfall 4: PBP re-ingestion required after migration
**What goes wrong:** Running `alembic upgrade head` adds the columns as NULL. Existing rows will have NULL for `air_yards`, `two_point_attempt`, `complete_pass`. Queries against existing data will return `successes=0` for all plays until data is re-ingested.
**Why it happens:** `to_sql(if_exists='append')` does not update existing rows. ALTER TABLE only adds columns; it does not backfill.
**How to avoid:** After migration, existing plays will have NULL for new columns. The quant query uses `WHERE two_point_attempt = 0` — NULL != 0, so NULL rows are excluded from results. For new PBP data loaded after migration, columns will be populated. The success criteria only requires `run_quant_query` returns non-None `true_probability` — this requires adequate sample of non-NULL rows (MIN_SAMPLE_SIZE=30). For testing, inject fixture rows with non-NULL values.
**Warning signs:** `result.data_source == "insufficient_sample"` after migration with empty or NULL-filled play_by_play. Solution: re-ingest one or more seasons.

### Pitfall 5: `is_stale` raises TypeError on naive datetime
**What goes wrong:** If `odds_snapshot.snapped_at` somehow loses timezone info, `is_stale()` raises `TypeError: snapped_at must be timezone-aware`.
**Why it happens:** `_extract_odds_snapshot` sets `snapped_at=datetime.now(timezone.utc)` — always tz-aware. This pitfall is a defensive concern only.
**How to avoid:** No change needed. The TypeError is correct behavior per `is_stale()` contract. The existing test `test_staleness_guard_rejects_stale` already covers the tz-aware case.

### Pitfall 6: Staleness gate fires on freshly fetched odds
**What goes wrong:** `_extract_odds_snapshot` stamps `snapped_at=datetime.now(timezone.utc)` at extraction time. The snapshot is immediately checked with `is_stale()`. Age is ~0 seconds — will never be stale at this point.
**Why it happens:** The staleness guard is designed for odds payloads that were fetched earlier and are being re-used (e.g., passed from a cache). In the current synchronous fetch-then-check flow, the snapshot is always fresh.
**How to avoid:** The guard is still correct to wire — it ensures the contract holds if the flow ever changes (e.g., memoized responses). The unit test for CTXT-02 wiring should use a fixture with a manually backdated `snapped_at` to exercise the rejection path.

---

## Code Examples

### GAP-1: Add columns to PlayByPlay ORM
```python
# Source: src/sportsbet/db/models.py — add to PlayByPlay class
air_yards: Mapped[Optional[int]] = mapped_column(SmallInteger)
two_point_attempt: Mapped[Optional[int]] = mapped_column(SmallInteger)
complete_pass: Mapped[Optional[int]] = mapped_column(SmallInteger)
```

### GAP-1: Alembic migration 0003
```python
# alembic/versions/0003_add_pbp_quant_columns.py
revision = "0003_add_pbp_quant_columns"
down_revision = "0002_add_injury_reports"

def upgrade() -> None:
    op.add_column("play_by_play", sa.Column("air_yards", sa.SmallInteger(), nullable=True))
    op.add_column("play_by_play", sa.Column("two_point_attempt", sa.SmallInteger(), nullable=True))
    op.add_column("play_by_play", sa.Column("complete_pass", sa.SmallInteger(), nullable=True))

def downgrade() -> None:
    op.drop_column("play_by_play", "complete_pass")
    op.drop_column("play_by_play", "two_point_attempt")
    op.drop_column("play_by_play", "air_yards")
```

### GAP-1: PBP_COLUMNS whitelist expansion
```python
# src/sportsbet/ingestion/pbp.py — PBP_COLUMNS list, append three entries
# New count: 21 columns (was 18)
PBP_COLUMNS: list[str] = [
    # ... existing 18 columns ...
    "air_yards",
    "two_point_attempt",
    "complete_pass",
]
```

### GAP-2: Staleness gate in make_context_agent
```python
# src/sportsbet/graph/agents.py — inside make_context_agent closure body
# Insert after the _extract_odds_snapshot() call (Step 1):
from sportsbet.ingestion.odds_poller import is_stale as _is_stale

if odds_snapshot is not None and _is_stale(odds_snapshot.snapped_at):
    log.warning(
        "context_agent_stale_odds_rejected",
        session_id=session_id,
        snapped_at=str(odds_snapshot.snapped_at),
    )
    odds_snapshot = None
```

### GAP-3 (Option A): Add american_odds field to AgentOddsSnapshot
```python
# src/sportsbet/graph/models.py — AgentOddsSnapshot
american_odds: Optional[int] = None  # Raw American odds integer from Odds API (e.g. -110)
```

### GAP-3 (Option A): Populate american_odds in _extract_odds_snapshot
```python
# src/sportsbet/graph/agents.py — _extract_odds_snapshot()
# prices[0] is already in scope — the raw int from outcomes[0]["price"]
return AgentOddsSnapshot(
    game_id=game_id,
    sportsbook=bookmaker.get("key", "unknown"),
    market_type="h2h",
    implied_probability=fair_prob,
    snapped_at=datetime.now(timezone.utc),
    american_odds=prices[0],  # store raw int for CLV persistence
)
```

### GAP-3 (Option A): Fix write call in make_context_agent
```python
# src/sportsbet/graph/agents.py — Step 1b, OddsSnapshotCreate construction
snap_create = OddsSnapshotCreate(
    game_id=odds_snapshot.game_id,
    sportsbook=odds_snapshot.sportsbook,
    market_type=odds_snapshot.market_type,
    price=odds_snapshot.american_odds,  # non-None int for CLV
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PBP_COLUMNS had 18 columns | Must be 21 after Phase 9 | Phase 9 | Existing ingested data lacks new columns; re-ingestion required for full backfill |
| `price=None` on every DB write | Non-null American odds int | Phase 9 | Enables CLV query: `SELECT price, snapped_at FROM odds_snapshots WHERE game_id=... ORDER BY snapped_at DESC LIMIT 1` |
| Stale odds forwarded unconditionally | Stale odds nulled before ContextSignals | Phase 9 | Arbitrage Agent will not receive stale probability reference |

**Deprecated/outdated after Phase 9:**
- `test_context_agent_persists_odds_snapshot` assertion `price is None` — must be updated to assert non-None after GAP-3 fix
- Comment in `agents.py` Step 1b: `"AgentOddsSnapshot stores Decimal probability, not int American odds"` — no longer accurate after adding `american_odds` field

---

## Open Questions

1. **GAP-3 storage strategy: American int vs. Decimal column**
   - What we know: `OddsSnapshot.price` is SmallInteger, typed for American odds. `AgentOddsSnapshot.implied_probability` is Decimal. The two are incompatible without conversion.
   - What's unclear: Whether CLV computation downstream needs the raw American odds or the devigged probability.
   - Recommendation: Option A (American odds int in `price`) is the lower-risk change — no new migration, no new column. CLV can be reconstructed from American odds. This phase should use Option A.

2. **PBP re-ingestion scope**
   - What we know: After migration, existing `play_by_play` rows will have NULL for new columns. The success criteria requires `run_quant_query` returns non-None `true_probability`.
   - What's unclear: Whether a full re-ingest is required or if inserting test fixture rows is sufficient for the success criterion test.
   - Recommendation: The live-DB integration test (success criterion 1) should insert fixture PBP rows with non-NULL `two_point_attempt=0`, `pass_touchdown=1`, `air_yards=15` directly via asyncpg to verify the query returns a real result without requiring a full season ingest.

3. **`test_pbp_columns_count` test**
   - What we know: `pbp.py` has a comment "Exactly 18 columns: verified by test_pbp_columns_count." No such test exists in `tests/`.
   - What's unclear: Whether a `test_pbp_columns_count` test exists elsewhere or the comment refers to a manual check.
   - Recommendation: Phase 9 plan should include updating the `PBP_COLUMNS` count comment from 18 to 21.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ with pytest-asyncio |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_quant.py tests/test_context.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QUANT-03 | `run_quant_query` against live DB returns non-None `true_probability` | integration (skipif no DB) | `pytest tests/test_quant.py::test_run_quant_query_passing -x` | Exists — test already written, currently raises column error |
| QUANT-01 | Pydantic gate + parameterized SQL executes without column error | unit (mock pool) | `pytest tests/test_quant.py::test_run_quant_query_mock_adequate_sample -x` | Exists — passes today (mock pool never hits real DB) |
| CTXT-02 | Stale odds snapshot (>5 min old) rejected: `context_signals.odds_snapshot is None` | unit (async) | `pytest tests/test_context.py::test_context_agent_rejects_stale_odds -x` | Does NOT exist — Wave 0 gap |
| DATA-03 | `write_odds_snapshot` writes non-null `price` | unit (mock) | `pytest tests/test_context.py::test_context_agent_persists_odds_snapshot -x` | Exists — currently asserts `price is None`; MUST be updated |
| ARBT-01 | Arbitrage agent returns non-None EVSignal when quant returns valid probability | integration (skipif no DB) | `pytest tests/test_quant.py::test_quant_agent_live -x` | Exists — currently asserts `data_source != "fixture"` (will pass once QUANT-03 is fixed) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_quant.py tests/test_context.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_context.py::test_context_agent_rejects_stale_odds` — covers CTXT-02 wiring (staleness gate in `make_context_agent`). New test needed.
- [ ] Update `tests/test_context.py::test_context_agent_persists_odds_snapshot` — change assertion from `price is None` to `price is not None` after GAP-3 fix.
- [ ] Integration test for QUANT-03: insert fixture PBP rows (with `air_yards`, `two_point_attempt`, `complete_pass`) then call `run_quant_query` against live DB to verify non-None `true_probability`.

---

## Sources

### Primary (HIGH confidence)
- Direct file read: `src/sportsbet/quant/query_builder.py` — SQL templates referencing absent columns confirmed
- Direct file read: `src/sportsbet/db/models.py` — PlayByPlay ORM columns confirmed absent
- Direct file read: `src/sportsbet/ingestion/pbp.py` — PBP_COLUMNS whitelist confirmed (18 columns, missing 3)
- Direct file read: `src/sportsbet/graph/agents.py` — `make_context_agent` confirmed: `is_stale` never imported or called; `price=None` hardcoded at line 200
- Direct file read: `src/sportsbet/ingestion/odds_poller.py` — `is_stale()` fully implemented, exported, and tested but unused in production path
- Direct file read: `alembic/versions/0001_initial_schema.py` — DDL confirmed: `play_by_play` has 18 columns, no `air_yards`/`two_point_attempt`/`complete_pass`
- Direct file read: `alembic/versions/0002_add_injury_reports.py` — `revision = "0002_add_injury_reports"` confirmed for `down_revision` chaining
- Direct file read: `.planning/v1.0-MILESTONE-AUDIT.md` — Gap definitions, severity ratings, and fix prescriptions confirmed
- Direct file read: `tests/test_context.py` — test at line 425 asserts `price is None` (must be updated in GAP-3 fix)

### Secondary (MEDIUM confidence)
- nflreadpy field name `air_yards`, `two_point_attempt`, `complete_pass` — inferred from nflreadpy being a renamed wrapper of the original NFL data py library, which documents these as standard PBP fields. Confidence: MEDIUM — exact field names should be verified with `nfl.load_pbp([2023]).columns` before writing the whitelist addition.

---

## Metadata

**Confidence breakdown:**
- GAP-1 diagnosis: HIGH — confirmed by reading query_builder.py SQL and models.py ORM side by side
- GAP-1 fix approach: HIGH — established migration pattern is clear from 0001/0002
- GAP-2 diagnosis: HIGH — confirmed by reading agents.py (no `is_stale` call) and odds_poller.py (function exists)
- GAP-2 fix approach: HIGH — two-line change following established closure import pattern
- GAP-3 diagnosis: HIGH — confirmed `price=None` at agents.py line 200
- GAP-3 fix approach (Option A): MEDIUM — `american_odds` field addition is sound but requires verifying `AgentOddsSnapshot.model_config = strict=True` accepts `Optional[int]` (it does, based on existing `Optional` fields on the model)
- nflreadpy column names: MEDIUM — standard NFL PBP column names, not yet verified against live `nfl.load_pbp()` output

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable codebase; gaps are not moving targets)
