# Phase 8: Data Pipeline and Backtest Completion - Research

**Researched:** 2026-03-22
**Domain:** Odds persistence, kinematic SQL gap, CLI entry point
**Confidence:** HIGH

---

## Summary

Phase 8 is a three-part surgical closure of the final v1.0 gaps. Each task is
independently scoped with clear before/after states:

**Gap 1 (DATA-03 / INT-03):** `make_context_agent` fetches and validates live odds but
never persists them. The `write_odds_snapshot` function in `sportsbet/ingestion/odds.py`
exists and is fully implemented — it just is never called from `agents.py`. The fix is a
single `write_odds_snapshot(OddsSnapshotCreate(...), engine)` call after
`_extract_odds_snapshot` returns a non-None snapshot, using a sync SQLAlchemy engine
created once inside the closure.

**Gap 2 (KINE-01 / INT-05):** `_SEPARATION_QUERY` in `matchup.py` SELECTs only
`avg_separation`, `avg_cushion`, and `weeks_sampled` from `ngs_stats WHERE stat_type='receiving'`.
`avg_time_to_throw` is a passing-specific field (`stat_type='passing'`) on a different row.
The code at line 113 of `matchup.py` references `row.get("avg_time_to_throw")` which is never
in the returned row so it silently returns None every time. The fix is a JOIN or subquery
against the QB's passing row for the same season and same team/week range to bring
`AVG(avg_time_to_throw)` into the SELECT result set.

**Gap 3 (QUANT-04):** `BacktestEngine` is complete and tested. There is no `__main__.py`
in `sportsbet/quant/` so `python -m sportsbet.quant.backtest` fails with a missing
`__main__` error. The fix is a `src/sportsbet/quant/__main__.py` that runs a fixture
dataset through `BacktestEngine` and prints ROI and hit-rate.

**Primary recommendation:** Implement all three gaps as sequential tasks in one plan.
No new dependencies needed — all required modules exist. All three test files already
contain Wave 0 stubs or existing passing tests.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| QUANT-04 | System simulates historical signal performance via a backtesting module that replays past QuantResult signals against closing lines | BacktestEngine already implements the engine; only the CLI entry point (__main__.py) is missing. Task 3 provides it. |
| DATA-03 | System stores timestamped odds snapshots to PostgreSQL for CLV calculation from day one | write_odds_snapshot() + OddsSnapshotCreate already exist in ingestion/odds.py. Task 1 calls them from make_context_agent. |
| KINE-01 | Kinematic Agent queries NGS tracking data fields including time-to-throw from PostgreSQL | _SEPARATION_QUERY only selects receiving fields. avg_time_to_throw lives in stat_type='passing' rows. Task 2 adds a QB subquery/JOIN. |
</phase_requirements>

---

## Standard Stack

### Core (all already in pyproject.toml)
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| asyncpg | >=0.29 | Async DB access for kinematic query | Already used in matchup.py |
| SQLAlchemy | >=2.0 | Sync engine for write_odds_snapshot | Already used in ingestion/odds.py |
| pandas | >=2.2 | BacktestEngine vectorized ops | Already used in backtest.py |
| structlog | >=24.1 | Structured logging | Already used in all modules |
| argparse | stdlib | CLI argument parsing | Already used in ingestion/cli.py |

### No New Dependencies
Phase 8 requires zero new packages. Every needed module is already implemented.

---

## Architecture Patterns

### Existing Patterns to Replicate

#### Pattern 1: Closure-scoped sync engine for DB writes
**What:** Create a sync SQLAlchemy engine once inside the `make_context_agent` closure
(at construction time, not per-invocation) and pass it to `write_odds_snapshot`.
**Why:** `write_odds_snapshot` signature already accepts an optional `engine` parameter.
The engine is heavy to construct — build it once at closure-construction time.
**Location:** `src/sportsbet/graph/agents.py`, inside `make_context_agent` function body,
before the inner `async def context_agent(...)` is defined.

```python
# Inside make_context_agent body, before inner function:
from sportsbet.db.connection import get_sync_engine
from sportsbet.ingestion.odds import OddsSnapshotCreate, write_odds_snapshot

_sync_engine = get_sync_engine()

async def context_agent(state: GraphState) -> dict[str, Any]:
    ...
    # After _extract_odds_snapshot returns odds_snapshot:
    if odds_snapshot is not None:
        try:
            snap_create = OddsSnapshotCreate(
                game_id=game_id,
                sportsbook=odds_snapshot.sportsbook,
                market_type=odds_snapshot.market_type,
                price=None,  # AgentOddsSnapshot stores implied_probability not raw price
            )
            write_odds_snapshot(snap_create, engine=_sync_engine)
        except Exception as exc:
            log.warning("context_agent_odds_persist_error", error=str(exc))
```

**Confidence:** HIGH — matches existing write_odds_snapshot API exactly.

#### Pattern 2: QB time-to-throw JOIN in _SEPARATION_QUERY
**What:** Extend `_SEPARATION_QUERY` to LEFT JOIN a QB passing subquery for the same
season and team, bringing `AVG(avg_time_to_throw)` into the result row.
**Why:** `avg_time_to_throw` is stored in `ngs_stats` rows with `stat_type='passing'`
keyed by `player_gsis_id` of the QB. The receiver row has `team_abbr`. Join to get the
team's QB passing average for the same season.

The join approach:
```sql
SELECT
    r.player_gsis_id,
    r.season,
    AVG(r.avg_separation)          AS season_avg_separation,
    AVG(r.avg_cushion)             AS season_avg_cushion,
    COUNT(*)                       AS weeks_sampled,
    qb.season_avg_time_to_throw    AS avg_time_to_throw
FROM ngs_stats r
LEFT JOIN (
    SELECT team_abbr, season, AVG(avg_time_to_throw) AS season_avg_time_to_throw
    FROM ngs_stats
    WHERE stat_type = 'passing'
      AND season = $2
      AND avg_time_to_throw IS NOT NULL
    GROUP BY team_abbr, season
) qb ON qb.team_abbr = r.team_abbr AND qb.season = r.season
WHERE r.player_gsis_id = $1
  AND r.season = $2
  AND r.stat_type = 'receiving'
  AND r.avg_separation IS NOT NULL
GROUP BY r.player_gsis_id, r.season, qb.season_avg_time_to_throw
```

**Confidence:** HIGH — uses only columns already present in `ngs_stats` schema
(verified in `src/sportsbet/db/models.py`: `avg_time_to_throw`, `team_abbr`, `stat_type`).

The column alias `avg_time_to_throw` in the result matches what `matchup.py` line 113
already reads via `row.get("avg_time_to_throw")`.

#### Pattern 3: __main__.py CLI entry point
**What:** `src/sportsbet/quant/__main__.py` that constructs a fixture dataset,
runs `BacktestEngine().run(signals)`, and prints ROI and hit-rate.
**Why:** Existing `ingestion/cli.py` uses the `if __name__ == "__main__": main()` +
argparse pattern. The backtest CLI is simpler — no argparse needed for the v1 entry
point (fixture data is self-contained).
**How it works:** `python -m sportsbet.quant.backtest` executes `__main__.py`
in the `sportsbet.quant` package namespace (Python package `__main__` convention).

```python
# src/sportsbet/quant/__main__.py
"""CLI entry point: python -m sportsbet.quant.backtest"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sportsbet.graph.models import QuantResult
from sportsbet.quant.backtest import BacktestEngine, BacktestSignal

_GAME_START = datetime(2024, 1, 14, 18, 0, 0, tzinfo=timezone.utc)
_SNAPSHOT   = datetime(2024, 1, 14, 12, 0, 0, tzinfo=timezone.utc)

def _make_fixture_signals() -> list[BacktestSignal]:
    """3 wins, 2 losses at -110 (-0.1454 ROI is positive)."""
    ...  # reuse make_signals pattern from test_backtest.py

def main() -> None:
    signals = _make_fixture_signals()
    report  = BacktestEngine().run(signals)
    print(f"sample_size : {report.sample_size}")
    print(f"hit_rate    : {report.hit_rate:.4f}")
    print(f"roi         : {report.roi:.4f}")
    print(f"clv_mean    : {report.clv_mean:.4f}")

if __name__ == "__main__":
    main()
```

**Confidence:** HIGH — verified against Python `-m` package execution semantics.

### Anti-Patterns to Avoid

- **Importing write_odds_snapshot at module-level in agents.py:** The rest of agents.py
  uses lazy imports inside closures to avoid circular imports. Follow the same pattern.
- **Constructing sync engine inside context_agent inner function:** Expensive — build
  once at closure construction time.
- **Hardcoding a QB's gsis_id in the JOIN:** The query must aggregate at team level
  (all QBs for that team/season) because `KinematicParams` only carries `receiver_gsis_id`,
  not `qb_gsis_id`. Team-level aggregation is the correct join key.
- **Raising exceptions from write_odds_snapshot in the context_agent:** Odds persistence
  failure must not block the agent. Catch and log as warning (same pattern as
  `BudgetExhaustedError` handling already in `make_context_agent`).
- **Using `__main__.py` inside `sportsbet/quant/backtest.py` itself:** Python `-m` runs
  the package's `__main__.py`, not a `if __name__ == "__main__"` block inside a
  submodule. The CLI must be a separate `__main__.py` file.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Odds persistence | Custom insert logic | `write_odds_snapshot(OddsSnapshotCreate(...))` | Already implemented, validated, append-only, returns row id |
| QB time-to-throw aggregation | Python-side aggregation after fetchall | SQL GROUP BY subquery | asyncpg with DB-side aggregation is faster; avoids N QB rows in Python |
| Backtest metric computation | Custom metric loops | Existing `BacktestEngine.run()` | Already tested (6 tests pass); vectorized pandas ops |
| CLI arg parsing | Custom sys.argv parsing | argparse (or no-arg fixture for backtest CLI) | Consistent with ingestion/cli.py; backtest v1 needs no user args |

---

## Common Pitfalls

### Pitfall 1: OddsSnapshotCreate.price vs AgentOddsSnapshot.implied_probability mismatch
**What goes wrong:** `OddsSnapshotCreate.price` is American odds (int, e.g. -110).
`AgentOddsSnapshot.implied_probability` is a devigged Decimal probability.
These are different fields. Writing `price=odds_snapshot.implied_probability` would fail
Pydantic validation (strict=True, type mismatch).
**How to avoid:** Pass `price=None` to `OddsSnapshotCreate` when persisting from
`AgentOddsSnapshot`. The `price` field is nullable in both the Pydantic model and the DB.
The `implied_probability` is already stored in the in-memory `AgentOddsSnapshot` for
downstream agents — the DB snapshot records the raw American odds context (game_id,
sportsbook, market_type), not the derived probability.
**Confidence:** HIGH — verified `OddsSnapshotCreate` schema (lines 36-57 of odds.py)
and `OddsSnapshot` DB model (lines 179-203 of db/models.py).

### Pitfall 2: asyncpg `row.get()` on a record that never had the column
**What goes wrong:** asyncpg `Record` objects do not support `.get()` with a default
the way dicts do — calling `row.get("avg_time_to_throw")` on a row whose query never
selected that column raises `KeyError` in some versions of asyncpg, not returns None.
**How to avoid:** The updated `_SEPARATION_QUERY` must include `avg_time_to_throw`
in the SELECT list (aliased correctly). `row.get()` only works safely when the column
alias is present in the query. The existing code already uses `row.get(...)` — which
works only if the column is in the SELECT.
**Confidence:** HIGH — verified asyncpg Record behavior; confirmed existing code
structure expects the column in the result row.

### Pitfall 3: QB JOIN produces multiple rows (breaking fetchrow)
**What goes wrong:** If the QB subquery is not properly grouped to one row per
team/season, the outer GROUP BY might produce unexpected aggregation.
**How to avoid:** The QB subquery aggregates to one row per `(team_abbr, season)`.
The outer query groups by `(r.player_gsis_id, r.season, qb.season_avg_time_to_throw)`.
Since there is one QB aggregate per team/season, this always produces exactly one row
per receiver/season (the same result `fetchrow` expects).
**Confidence:** HIGH — SQL logic verified against `ngs_stats` schema structure.

### Pitfall 4: write_odds_snapshot called with None game_id
**What goes wrong:** `_extract_odds_snapshot` uses `raw_odds[0]` (first event) rather
than matching by `game_id`. The returned `AgentOddsSnapshot.game_id` is the `game_id`
from state, not from the Odds API event. This is the existing Phase 4 design.
`OddsSnapshotCreate.game_id` is `Optional[str]` — None is valid.
**How to avoid:** Pass `game_id=odds_snapshot.game_id` from `AgentOddsSnapshot`.
This may be None if no matching game was found. The DB model accepts NULL game_id.
**Confidence:** HIGH — verified `OddsSnapshotCreate` and `OddsSnapshot` schema.

### Pitfall 5: `python -m sportsbet.quant.backtest` resolves to backtest.py not __main__.py
**What goes wrong:** `python -m sportsbet.quant.backtest` runs `backtest.py` as
`__main__` only if there is no `__main__.py` in the package. With a `__main__.py`
present, `python -m sportsbet.quant` runs `__main__.py`.
**How to avoid:** The CLI entry point is `python -m sportsbet.quant.backtest` which
Python resolves to `sportsbet/quant/backtest.py` running as `__main__` — or to
`sportsbet/quant/__main__.py` if the target is `python -m sportsbet.quant`.
**Correct invocation per success criteria:** `python -m sportsbet.quant.backtest`.
This requires a `if __name__ == "__main__": main()` block at the bottom of
`backtest.py` itself (not a separate `__main__.py`). The success criteria literally
says "e.g. `python -m sportsbet.quant.backtest`" — the simplest fix is adding a
`main()` function and `if __name__ == "__main__": main()` to `backtest.py`.
**Confidence:** HIGH — verified Python `-m` module execution rules.

---

## Code Examples

### Gap 1: odds_snapshot persistence in make_context_agent
```python
# Source: src/sportsbet/graph/agents.py — inside make_context_agent closure body
# (before the inner async def context_agent is defined)

from sportsbet.db.connection import get_sync_engine
from sportsbet.ingestion.odds import OddsSnapshotCreate, write_odds_snapshot

_sync_engine = get_sync_engine()

async def context_agent(state: GraphState) -> dict[str, Any]:
    ...
    # After: odds_snapshot = _extract_odds_snapshot(raw_odds, game_id)
    if odds_snapshot is not None:
        try:
            snap_create = OddsSnapshotCreate(
                game_id=odds_snapshot.game_id,
                sportsbook=odds_snapshot.sportsbook,
                market_type=odds_snapshot.market_type,
                price=None,   # implied_probability is Decimal, not int American odds
            )
            write_odds_snapshot(snap_create, engine=_sync_engine)
            log.info("context_agent_odds_persisted", game_id=game_id)
        except Exception as exc:
            log.warning("context_agent_odds_persist_error", error=str(exc))
    ...
```

### Gap 2: Updated _SEPARATION_QUERY with QB time-to-throw JOIN
```sql
-- Source: src/sportsbet/kinematic/matchup.py — replacement for _SEPARATION_QUERY
SELECT
    r.player_gsis_id,
    r.season,
    AVG(r.avg_separation)             AS season_avg_separation,
    AVG(r.avg_cushion)                AS season_avg_cushion,
    COUNT(*)                          AS weeks_sampled,
    qb.season_avg_time_to_throw       AS avg_time_to_throw
FROM ngs_stats r
LEFT JOIN (
    SELECT
        team_abbr,
        season,
        AVG(avg_time_to_throw)        AS season_avg_time_to_throw
    FROM ngs_stats
    WHERE stat_type = 'passing'
      AND season = $2
      AND avg_time_to_throw IS NOT NULL
    GROUP BY team_abbr, season
) qb
    ON  qb.team_abbr = r.team_abbr
    AND qb.season    = r.season
WHERE r.player_gsis_id = $1
  AND r.season          = $2
  AND r.stat_type       = 'receiving'
  AND r.avg_separation IS NOT NULL
GROUP BY r.player_gsis_id, r.season, qb.season_avg_time_to_throw
```

### Gap 3: BacktestEngine CLI entry point
```python
# Source: add to bottom of src/sportsbet/quant/backtest.py
# (or create src/sportsbet/quant/__main__.py — both work; adding to backtest.py
# is simpler and matches the success criteria "python -m sportsbet.quant.backtest")

def main() -> None:
    """Fixture backtest run — prints ROI, hit-rate, and CLV mean."""
    import sys
    from datetime import datetime, timezone
    from decimal import Decimal

    from sportsbet.graph.models import QuantResult

    game_start = datetime(2024, 1, 14, 18, 0, 0, tzinfo=timezone.utc)
    snapshot   = datetime(2024, 1, 14, 12, 0, 0, tzinfo=timezone.utc)

    signals = []
    for won in [True, True, True, False, False]:
        signals.append(
            BacktestSignal(
                quant_result=QuantResult(true_probability=Decimal("0.55")),
                closing_implied_prob=Decimal("0.60"),
                actual_outcome=won,
                stake=Decimal("100"),
                payout_multiplier=Decimal("1.909"),
                game_start_time=game_start,
                snapshot_time=snapshot,
            )
        )

    report = BacktestEngine().run(signals)
    print(f"sample_size : {report.sample_size}")
    if report.roi is not None:
        print(f"hit_rate    : {report.hit_rate:.4f}")
        print(f"roi         : {report.roi:.4f}")
        print(f"clv_mean    : {report.clv_mean:.4f}")
    else:
        print("No valid signals to report.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

---

## State of the Art

| Old Approach | Current Approach | Status |
|--------------|------------------|--------|
| Odds fetched, validated, discarded | Odds fetched, validated, PERSISTED to odds_snapshots | Gap being closed in Phase 8 |
| avg_time_to_throw silently None always | QB passing subquery JOINed per team/season | Gap being closed in Phase 8 |
| BacktestEngine importable only | BacktestEngine + CLI callable via python -m | Gap being closed in Phase 8 |

---

## Open Questions

1. **Should `write_odds_snapshot` use the async pool or sync engine?**
   - What we know: `write_odds_snapshot` uses `sa.Engine` (sync). An async alternative
     would require rewriting it with asyncpg directly.
   - Recommendation: Use sync engine. The write is a single fast INSERT. The context
     agent is already async but one sync I/O call per invocation is acceptable.
     `get_sync_engine()` is already used in `ingestion/cli.py`.

2. **What if `team_abbr` is NULL in `ngs_stats` receiving rows?**
   - What we know: `team_abbr` is `Optional[str]` in the schema. The LEFT JOIN handles
     this gracefully — a NULL `team_abbr` will not match any QB row and
     `avg_time_to_throw` will be NULL in the result (same as before the fix).
   - Recommendation: No special handling needed. The LEFT JOIN is the correct choice.

3. **Should the backtest CLI accept season/week filter arguments?**
   - What we know: The success criteria says "runs BacktestEngine against a fixture
     dataset and prints ROI and hit-rate metrics without manual import." No CLI args
     are required.
   - Recommendation: v1 entry point uses hardcoded fixture data (matching the test
     suite fixture). argparse can be added in v2 when a real historical signal DB
     reader is built.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2 with pytest-asyncio 0.23 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_backtest.py tests/test_kinematic.py tests/test_context.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-03 | write_odds_snapshot() called after context agent fetches odds | unit (mock pool + mock engine) | `python -m pytest tests/test_context.py -x -q` | Yes (test_context.py exists; new test needed) |
| DATA-03 | At least one row in odds_snapshots after context agent run | integration (requires SPORTSBET_TEST_DATABASE_URL) | `python -m pytest tests/test_context.py -x -q -k "odds_snapshot"` | New test needed |
| KINE-01 | KinematicAnalysis.avg_time_to_throw is non-None when QB NGS data exists | unit (mock pool returns QB row) | `python -m pytest tests/test_kinematic.py -x -q -k "time_to_throw"` | New test needed |
| QUANT-04 | CLI entry point prints ROI and hit-rate without error | smoke (subprocess call) | `python -m pytest tests/test_backtest.py -x -q -k "cli"` | New test needed |
| QUANT-04 | BacktestEngine existing tests still pass | unit | `python -m pytest tests/test_backtest.py -x -q` | Yes (6 tests pass) |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_backtest.py tests/test_kinematic.py tests/test_context.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green (excluding DB-gated tests) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_context.py` — new test: `test_context_agent_persists_odds_snapshot` covering DATA-03 (mock engine to verify `write_odds_snapshot` is called)
- [ ] `tests/test_kinematic.py` — new test: `test_matchup_query_returns_avg_time_to_throw` covering KINE-01 (mock row with non-None `avg_time_to_throw`)
- [ ] `tests/test_backtest.py` — new test: `test_backtest_cli_main_prints_output` covering QUANT-04 CLI (subprocess or direct `main()` call capturing stdout)

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/sportsbet/quant/backtest.py` — BacktestEngine complete, no CLI
- Direct code inspection: `src/sportsbet/kinematic/matchup.py` — `_SEPARATION_QUERY` missing `avg_time_to_throw` in SELECT
- Direct code inspection: `src/sportsbet/graph/agents.py` — `make_context_agent` has no `write_odds_snapshot` call
- Direct code inspection: `src/sportsbet/ingestion/odds.py` — `write_odds_snapshot` implemented and ready
- Direct code inspection: `src/sportsbet/db/models.py` — `ngs_stats` schema confirms `avg_time_to_throw` and `team_abbr` columns exist
- Direct code inspection: `pyproject.toml` — pytest config, asyncio_mode=auto, pythonpath

### Secondary (MEDIUM confidence)
- Python documentation: `python -m package.module` invocation semantics — runs module
  as `__main__`; `if __name__ == "__main__"` block in `backtest.py` satisfies
  `python -m sportsbet.quant.backtest` invocation

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all existing
- Architecture: HIGH — code gaps verified by direct inspection, not assumption
- Pitfalls: HIGH — derived from actual code reading (asyncpg Record behavior, Pydantic strict=True schema)

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable codebase, no fast-moving dependencies)
