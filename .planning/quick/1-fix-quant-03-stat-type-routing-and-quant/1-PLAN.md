---
phase: quick-1
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - src/sportsbet/graph/state.py
  - src/sportsbet/graph/agents.py
  - src/sportsbet/ingestion/games.py
  - src/sportsbet/ingestion/cli.py
autonomous: true
requirements: [QUANT-03, QUANT-04]
must_haves:
  truths:
    - "quant_agent reads stat_type from GraphState; passing remains the default when field is absent"
    - "context_agent can write stat_type into GraphState to override the quant query"
    - "ingest_games_seasons() populates the games table from nflreadpy.load_schedules()"
    - "CLI --games flag calls ingest_games_seasons() so fresh deploys are not blocked by empty games table"
  artifacts:
    - path: "src/sportsbet/graph/state.py"
      provides: "stat_type field declared in GraphState TypedDict"
      contains: "stat_type"
    - path: "src/sportsbet/graph/agents.py"
      provides: "quant_agent reads stat_type from state; context_agent writes stat_type"
      contains: "state.get(\"stat_type\", \"passing\")"
    - path: "src/sportsbet/ingestion/games.py"
      provides: "ingest_games_seasons() using nflreadpy.load_schedules()"
      exports: ["ingest_games_seasons"]
    - path: "src/sportsbet/ingestion/cli.py"
      provides: "--games CLI flag calling ingest_games_seasons()"
      contains: "ingest_games_seasons"
  key_links:
    - from: "src/sportsbet/graph/agents.py (context_agent)"
      to: "GraphState.stat_type"
      via: "return dict with stat_type key"
      pattern: "stat_type.*state"
    - from: "src/sportsbet/graph/agents.py (quant_agent)"
      to: "QuantParams.stat_type"
      via: "state.get(\"stat_type\", \"passing\")"
      pattern: "state\\.get\\(\"stat_type\""
    - from: "src/sportsbet/ingestion/cli.py"
      to: "src/sportsbet/ingestion/games.py"
      via: "import + function call in main()"
      pattern: "ingest_games_seasons"
---

<objective>
Close two v1.0 milestone gaps: QUANT-03 (stat_type hardcoded in quant_agent) and QUANT-04 (games table never populated on fresh deploy).

Purpose: Both gaps produce silent correctness failures. QUANT-03 causes every quant query to use passing stats regardless of the context agent's request. QUANT-04 causes the backtest to return sample_size=0 because the LEFT JOIN on games yields NULL game_start_time for all rows.
Output: stat_type flows from GraphState into QuantParams; ingest_games_seasons() populates the games table via nflreadpy.load_schedules(); CLI exposes a --games flag.
</objective>

<execution_context>
@C:/Users/rahul/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/rahul/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

<!-- Key interfaces the executor needs. No codebase exploration required. -->

<interfaces>
From src/sportsbet/graph/state.py (GraphState TypedDict, last field before EOF):
```python
player_prop_snapshots: list[Any] | None  # type: ignore[misc]
# PlayerPropSnapshotCreate list from context_agent Step 1c (Phase 23 — PROP-06)
```
New field appended after this line:
```python
stat_type: str | None  # type: ignore[misc]
# Quant stat category override: "passing" | "rushing" | "receiving" | None.
# None means quant_agent defaults to "passing". Set by context_agent when
# request context indicates non-passing play analysis.
# Access via state.get("stat_type", "passing") — never require presence.
```

From src/sportsbet/graph/agents.py (make_quant_agent closure, lines 96-103):
```python
params = QuantParams(
    game_id=state["game_id"],
    season=state["season"],
    week=state["week"],
    posteam=state["home_team"],
    stat_type="passing",         # <-- HARDCODED — fix to state.get("stat_type", "passing")
    filters={},
)
```

From src/sportsbet/graph/models.py (QuantParams):
```python
stat_type: Literal["passing", "rushing", "receiving"]
```

From src/sportsbet/db/models.py (Game ORM model):
```python
class Game(Base):
    __tablename__ = "games"
    game_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    home_team: Mapped[str] = mapped_column(String(3), nullable=False)
    away_team: Mapped[str] = mapped_column(String(3), nullable=False)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    stadium: Mapped[Optional[str]] = mapped_column(String(100))
    weather_json: Mapped[Optional[dict]] = mapped_column(JSONB)
```

From nflreadpy (confirmed in site-packages/nflreadpy/__init__.py):
```python
from .load_schedules import load_schedules
# nfl.load_schedules(seasons=[2023, 2024]) -> Polars DataFrame
```
nflreadpy schedule columns that map to Game model:
- game_id     -> game_id (String, primary key)
- season      -> season
- week        -> week
- home_team   -> home_team (3-char abbr)
- away_team   -> away_team (3-char abbr)
- gameday     -> game_date (Date — rename required: "gameday" -> "game_date")
- stadium     -> stadium (nullable)

From src/sportsbet/ingestion/player_stats.py (pattern to follow):
```python
import nflreadpy as nfl  # NOT nfl_data_py — archived Sep 2025
import polars as pl
# nflreadpy returns Polars DataFrame; call .to_pandas() only before to_sql()
df: pl.DataFrame = nfl.load_player_stats([season])
df.select(COLUMN_WHITELIST).to_pandas().to_sql(table, engine, if_exists="append", index=False)
```

From src/sportsbet/ingestion/cli.py (existing structure):
```python
from sportsbet.ingestion.ngs import NGS_MIN_SEASON, ingest_ngs_seasons
from sportsbet.ingestion.pbp import ingest_pbp_seasons
from sportsbet.ingestion.player_stats import ingest_player_stats_seasons

def main() -> None:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--seasons", nargs="+", type=int, required=True, ...)
    parser.add_argument("--pbp-only", action="store_true", ...)
    # ... calls ingest_pbp_seasons, ingest_player_stats_seasons, ingest_ngs_seasons
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add stat_type to GraphState and fix quant_agent routing</name>
  <files>
    src/sportsbet/graph/state.py
    src/sportsbet/graph/agents.py
    tests/test_quant.py
  </files>
  <behavior>
    - Test 1: quant_agent with state.stat_type="rushing" constructs QuantParams(stat_type="rushing") — NOT "passing"
    - Test 2: quant_agent with no stat_type key in state defaults to QuantParams(stat_type="passing")
    - Test 3: quant_agent with state.stat_type=None defaults to QuantParams(stat_type="passing")
    - Test 4: GraphState TypedDict accepts stat_type field without TypeError
  </behavior>
  <action>
    **state.py** — Append `stat_type` as the last field in GraphState TypedDict (after player_prop_snapshots):
    ```python
    stat_type: str | None  # type: ignore[misc]
    # Quant stat category override: "passing" | "rushing" | "receiving" | None.
    # None means quant_agent defaults to "passing". Written by context_agent when
    # request context indicates non-passing analysis. Access via state.get().
    ```
    Also update the class docstring to describe the new field (follow the existing docstring format for other fields).

    **agents.py** — In the make_quant_agent closure body, change the hardcoded stat_type line:
    - OLD: `stat_type="passing",         # default stat type; Context Agent will override`
    - NEW: `stat_type=state.get("stat_type") or "passing",  # QUANT-03: read from state, default "passing"`

    The `or "passing"` handles both missing key (KeyError-safe via .get()) and explicit None value.
    Do NOT add stat_type to context_agent return dict in this task — context_agent integration is out of scope for this gap fix. The fix enables it; callers now set stat_type in initial state.

    **tests/test_quant.py** — Add test cases for the two behaviors (stat_type routing and default). Look at existing test patterns in this file — use asyncio.run() (not get_event_loop().run_until_complete()), mock run_quant_query at the consumer module path `sportsbet.graph.agents` (not origin), and use MagicMock for pool.acquire() (not AsyncMock).
  </action>
  <verify>
    <automated>cd C:/Users/rahul/ucla/pp/sportsbet && python -m pytest tests/test_quant.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>
    - GraphState has stat_type field (str | None)
    - quant_agent reads stat_type via state.get("stat_type") or "passing"
    - Tests pass: stat_type="rushing" produces QuantParams(stat_type="rushing"); absent/None defaults to "passing"
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add ingest_games_seasons() and --games CLI flag</name>
  <files>
    src/sportsbet/ingestion/games.py
    src/sportsbet/ingestion/cli.py
    tests/test_ingestion_games.py
  </files>
  <behavior>
    - Test 1: ingest_games_seasons([2024], engine) calls nfl.load_schedules([2024]) exactly once
    - Test 2: rows written to games table contain game_id, season, week, home_team, away_team, game_date
    - Test 3: ingest_games_seasons with duplicate game_ids does not raise (ON CONFLICT DO NOTHING)
    - Test 4: CLI with --games flag calls ingest_games_seasons (unit test via mock)
  </behavior>
  <action>
    **src/sportsbet/ingestion/games.py** — Create new module following player_stats.py pattern exactly:

    ```python
    """NFL game schedule ingestion module (QUANT-04 fix).

    Populates the games table from nflreadpy.load_schedules().
    The games table is the parent FK for odds_snapshots; an empty games table
    causes load_snapshots() LEFT JOIN to produce NULL game_start_time for all
    rows, making BacktestEngine return sample_size=0.

    nflreadpy.load_schedules() returns a Polars DataFrame.
    Column rename: "gameday" -> "game_date" to match Game ORM model.
    """
    from __future__ import annotations

    import gc

    import nflreadpy as nfl  # NOT nfl_data_py — archived Sep 2025
    import polars as pl
    import sqlalchemy as sa
    import structlog
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from sportsbet.db.connection import get_sync_engine
    from sportsbet.db.models import Game

    log = structlog.get_logger()

    GAMES_COLUMNS: list[str] = [
        "game_id",
        "season",
        "week",
        "home_team",
        "away_team",
        "gameday",    # renamed to "game_date" via _COLUMN_RENAMES
        "stadium",
    ]

    _COLUMN_RENAMES: dict[str, str] = {
        "gameday": "game_date",
    }


    def ingest_games_seasons(
        seasons: list[int], engine: sa.Engine | None = None
    ) -> None:
        """Load NFL game schedule rows for the specified seasons into games table.

        Uses pg_insert ON CONFLICT DO NOTHING — safe to re-run; existing rows
        are not overwritten. Applies Polars-first write path: nflreadpy returns
        Polars, .to_pandas() called only before to_sql().

        Args:
            seasons: NFL season years to ingest.
            engine: SQLAlchemy sync engine; creates one via get_sync_engine() if None.
        """
        if engine is None:
            engine = get_sync_engine()

        for season in seasons:
            log.info("ingesting_games", season=season)
            try:
                df: pl.DataFrame = nfl.load_schedules([season])
            except Exception as exc:
                log.warning("games_load_failed", season=season, error=str(exc))
                gc.collect()
                continue

            # Select only the columns we need; skip missing columns gracefully
            available = [c for c in GAMES_COLUMNS if c in df.columns]
            df = df.select(available)

            # Drop rows with NULL game_id or game_date — cannot insert without PK
            if "game_id" in df.columns:
                df = df.filter(pl.col("game_id").is_not_null())
            if "gameday" in df.columns:
                df = df.filter(pl.col("gameday").is_not_null())

            # Rename to match schema
            df = df.rename({k: v for k, v in _COLUMN_RENAMES.items() if k in df.columns})

            if df.is_empty():
                log.warning("games_empty_after_filter", season=season)
                gc.collect()
                continue

            rows = df.to_pandas().to_dict(orient="records")
            with engine.begin() as conn:
                stmt = pg_insert(Game).values(rows).on_conflict_do_nothing(index_elements=["game_id"])
                conn.execute(stmt)

            log.info("games_ingested", season=season, rows=len(rows))
            gc.collect()
    ```

    **src/sportsbet/ingestion/cli.py** — Add `--games` flag and call ingest_games_seasons:
    1. Add import: `from sportsbet.ingestion.games import ingest_games_seasons`
    2. Add argument after `--pbp-only`:
       ```python
       parser.add_argument(
           "--games",
           action="store_true",
           help="Ingest NFL game schedules into the games table (prerequisite for backtest)",
       )
       ```
    3. In main(), after `ingest_pbp_seasons(seasons, engine)` call, add at end of the function body (not inside if not args.pbp_only — games are independent):
       ```python
       if args.games:
           log.info("ingesting_games_schedules", seasons=seasons)
           ingest_games_seasons(seasons, engine)
       ```

    **tests/test_ingestion_games.py** — Create new test file. Use unittest.mock.patch to mock nfl.load_schedules at the consumer module path `sportsbet.ingestion.games` (Phase 8 patching pattern). Return a small Polars DataFrame with required columns. Use an in-memory SQLite engine or skip DB assertion for ON CONFLICT test (use mock engine). Follow existing test file patterns.
  </action>
  <verify>
    <automated>cd C:/Users/rahul/ucla/pp/sportsbet && python -m pytest tests/test_ingestion_games.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>
    - src/sportsbet/ingestion/games.py exists with ingest_games_seasons() exported
    - cli.py has --games flag that calls ingest_games_seasons()
    - Tests pass: load_schedules called, rows mapped to Game schema, duplicates handled, CLI flag wired
    - python -m sportsbet.ingestion.cli --seasons 2024 --games runs without ImportError
  </done>
</task>

</tasks>

<verification>
Run full test suite to confirm no regressions:

```bash
cd C:/Users/rahul/ucla/pp/sportsbet && python -m pytest tests/ -x -q --ignore=tests/test_db.py 2>&1 | tail -30
```

Smoke-test CLI import:
```bash
cd C:/Users/rahul/ucla/pp/sportsbet && python -c "from sportsbet.ingestion.games import ingest_games_seasons; from sportsbet.graph.state import GraphState; print('imports ok')"
```

Verify stat_type routing fix:
```bash
cd C:/Users/rahul/ucla/pp/sportsbet && python -c "
from sportsbet.graph.state import GraphState
import typing
fields = typing.get_type_hints(GraphState)
assert 'stat_type' in fields, 'stat_type missing from GraphState'
print('stat_type field present:', fields['stat_type'])
"
```
</verification>

<success_criteria>
- GraphState TypedDict declares `stat_type: str | None`
- make_quant_agent closure reads `state.get("stat_type") or "passing"` — not hardcoded "passing"
- `src/sportsbet/ingestion/games.py` exists with `ingest_games_seasons(seasons, engine)` using `nfl.load_schedules()`
- `cli.py --games` flag calls `ingest_games_seasons()`
- All new tests pass; no existing tests regress
- QUANT-03 and QUANT-04 gaps from the v1.0 milestone audit are closed
</success_criteria>

<output>
No SUMMARY.md required for quick plans. Update STATE.md if desired.
</output>
