# Phase 1: Data Foundation - Research

**Researched:** 2026-03-10
**Domain:** PostgreSQL schema design, Alembic migrations, NFL data ingestion (nflreadpy), Polars DataFrames
**Confidence:** MEDIUM-HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DATA-01 | System stores NFL game, player, and play-by-play data in a PostgreSQL schema with composite indexes on season, week, player_id, and game_id | Schema DDL patterns, Alembic index creation, Pitfall 7 mitigation |
| DATA-02 | System ingests multi-season NFL PBP data via nfl_data_py using a year-by-year loading loop with column whitelist and gc.collect() to prevent OOM | nflreadpy API (nfl_data_py replacement), Polars memory patterns, Pitfall 4 mitigation |
| DATA-03 | System stores timestamped odds snapshots to PostgreSQL for CLV (closing line value) calculation from day one | odds_snapshots table design, append-only pattern, CLV-ready schema |
| DATA-04 | System manages schema versioning and migrations via Alembic | Alembic init patterns, op.create_index, env.py configuration |
</phase_requirements>

---

## Summary

Phase 1 builds the data foundation that every downstream agent depends on. The work is entirely standard — PostgreSQL schema design, Alembic migrations, and NFL data ingestion — but several setup-time decisions are expensive to retrofit, making this research critical to get right before any code is written.

**Critical discovery:** `nfl_data_py` was archived by the nflverse team on September 25, 2025 and is no longer maintained. The official replacement is `nflreadpy` (v0.1.5, November 2025). The DATA-02 requirement references `nfl_data_py` by name, but the planner must use `nflreadpy` instead. The API has changed: `import_pbp_data()` is replaced by `load_pbp(seasons=[...])`, which returns **Polars DataFrames** rather than pandas DataFrames. The memory management discipline (year-by-year loops, column pruning, gc.collect()) still applies.

**Primary recommendation:** Use `nflreadpy` for all NFL data ingestion. Define all composite indexes in the Alembic migration before loading any data. Use `if_exists='append'` with `ON CONFLICT DO NOTHING` on all PostgreSQL writes to prevent duplicate rows on re-runs.

---

## CRITICAL: nfl_data_py is Archived — Use nflreadpy

**Confidence: HIGH** (verified via WebFetch of the GitHub repository)

The nflverse team archived `nfl_data_py` on September 25, 2025 with this notice:

> "nfl_data_py has been deprecated in favour of nflreadpy. All future development will occur in nflreadpy and users are encouraged to switch immediately. No further nfl_data_py maintenance or updates are planned."

The DATA-02 requirement text ("via nfl_data_py") must be interpreted as "via the canonical nflverse Python package," which is now `nflreadpy`. The ingestion architecture described in DATA-02 (year-by-year loop, column whitelist, gc.collect()) remains valid — only the package name and function signatures change.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `postgresql` | 15+ | Primary data store | Project requirement; composite indexes, JSONB, TIMESTAMPTZ native support |
| `alembic` | `>=1.13` | Schema versioning and migrations | SQLAlchemy-native; required for multi-year NFL schema evolution per DATA-04 |
| `sqlalchemy` | `>=2.0` | ORM / schema definition for migrations | Alembic uses SQLAlchemy metadata; use for DDL only, not hot-path queries |
| `nflreadpy` | `>=0.1.5` | NFL PBP, player stats, NGS ingestion | Official nflverse Python package (replacement for archived nfl_data_py) |
| `polars` | `>=1.0` | DataFrame engine (returned by nflreadpy) | nflreadpy returns Polars DataFrames; ~40% lower memory than pandas on large datasets |
| `asyncpg` | `>=0.29` | Async PostgreSQL driver for runtime queries | Fastest async Postgres driver; used by downstream quant agents |
| `psycopg[binary]` | `>=3.2` | Sync driver for bulk ingestion writes | Preferred for `COPY`-style bulk writes during ingestion |
| `pydantic` | `>=2.7,<3.0` | Settings and data validation | pydantic-settings for DB connection config; native v2 patterns only |
| `pydantic-settings` | `>=2.3` | Typed environment variable loading | `BaseSettings` for DATABASE_URL and config at startup |
| `structlog` | `>=24.1` | Structured JSON logging | Agent run IDs and audit trail required from phase 1 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pandas` | `>=2.2` | DataFrame ops after Polars conversion | Use `.to_pandas()` when SQLAlchemy's `to_sql` is needed; prefer Polars natively |
| `pyarrow` | `>=16.0` | Arrow memory backend | Enables pandas Arrow dtype backend (`dtype_backend="arrow"`) for lower memory |
| `psutil` | `>=5.9` | Memory usage monitoring | Log `virtual_memory().percent` before/after each season load as OOM guard |
| `python-dotenv` | `>=1.0` | .env file loading | Local dev DATABASE_URL and credentials |
| `uv` | `>=0.4` | Package manager | Replaces pip; 10-100x faster installs; use `uv sync` with lockfile |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `nflreadpy` | `nfl_data_py` | nfl_data_py is archived (Sep 2025) — do not use |
| `nflreadpy` | nflfastR (R) | R-only; Python is required per project stack |
| `polars` direct | pandas only | nflreadpy returns Polars; converting to pandas adds memory overhead |
| `asyncpg` | `psycopg2` | psycopg2 is synchronous-only, maintenance mode — do not use |
| `alembic` | Django migrations | Not a Django project; Alembic is the standard SQLAlchemy tool |

**Installation:**

```bash
# Install uv first
curl -LsSf https://astral.sh/uv/install.sh | sh

# Initialize project
uv init sportsbet --python 3.12
cd sportsbet

# Phase 1 dependencies
uv add alembic sqlalchemy asyncpg "psycopg[binary]" nflreadpy polars pyarrow pandas pydantic "pydantic-settings" structlog psutil python-dotenv

# Dev dependencies
uv add --dev pytest pytest-asyncio mypy pyright
```

---

## Architecture Patterns

### Recommended Project Structure

```
sportsbet/
├── alembic/
│   ├── env.py                  # migration environment
│   ├── script.py.mako          # migration template
│   └── versions/
│       └── 0001_initial_schema.py   # tables + all composite indexes
├── src/
│   └── sportsbet/
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py       # SQLAlchemy ORM models (DDL source of truth)
│       │   ├── connection.py   # asyncpg pool + psycopg sync engine
│       │   └── migrations.py   # run_migrations() utility
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── pbp.py          # load_pbp year-by-year loop
│       │   ├── player_stats.py # load_player_stats ingestion
│       │   ├── ngs.py          # load_nextgen_stats (passing/receiving/rushing)
│       │   └── odds.py         # odds_snapshots writer
│       └── config.py           # pydantic-settings Settings class
├── tests/
│   ├── conftest.py
│   └── test_ingestion.py
├── pyproject.toml
└── alembic.ini
```

### Pattern 1: Alembic Initial Migration with Composite Indexes

**What:** All tables AND all composite indexes are defined in the first migration (version 0001). Indexes are in the migration before any `load_pbp()` call.

**When to use:** Always for this project. Indexes defined after data load require a full table scan to build, and the migration is the enforced contract.

**Example:**

```python
# alembic/versions/0001_initial_schema.py
# Source: Alembic official docs + project ARCHITECTURE.md

def upgrade() -> None:
    # games table
    op.create_table(
        "games",
        sa.Column("game_id", sa.String(20), primary_key=True),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("week", sa.SmallInteger(), nullable=False),
        sa.Column("home_team", sa.String(3), nullable=False),
        sa.Column("away_team", sa.String(3), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("stadium", sa.String(100), nullable=True),
        sa.Column("weather_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMPTZ(), server_default=sa.func.now()),
    )
    op.create_index("idx_games_season_week", "games", ["season", "week"])
    op.create_index("idx_games_teams", "games", ["home_team", "away_team"])

    # play_by_play table (key columns only — full schema per column whitelist)
    op.create_table(
        "play_by_play",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("game_id", sa.String(20), sa.ForeignKey("games.game_id")),
        sa.Column("play_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("week", sa.SmallInteger(), nullable=False),
        sa.Column("posteam", sa.String(3)),
        sa.Column("defteam", sa.String(3)),
        sa.Column("play_type", sa.String(20)),
        sa.Column("yards_gained", sa.SmallInteger()),
        sa.Column("down", sa.SmallInteger()),
        sa.Column("ydstogo", sa.SmallInteger()),
        sa.Column("passer_player_id", sa.String(20)),
        sa.Column("receiver_player_id", sa.String(20)),
        sa.Column("rusher_player_id", sa.String(20)),
        sa.Column("pass_touchdown", sa.SmallInteger()),
        sa.Column("rush_touchdown", sa.SmallInteger()),
        sa.Column("interception", sa.SmallInteger()),
        sa.Column("epa", sa.Numeric(8, 4)),
        sa.Column("wp", sa.Numeric(6, 4)),
        sa.UniqueConstraint("game_id", "play_id", name="uq_pbp_game_play"),
    )
    # Required composite indexes per PITFALLS.md Pitfall 7
    op.create_index("idx_pbp_season_week", "play_by_play", ["season", "week"])
    op.create_index("idx_pbp_posteam_season", "play_by_play", ["posteam", "season"])
    op.create_index("idx_pbp_defteam_season", "play_by_play", ["defteam", "season"])
    op.create_index("idx_pbp_play_type_season", "play_by_play", ["play_type", "season", "week"])
    op.create_index("idx_pbp_passer_season", "play_by_play", ["passer_player_id", "season"])
    op.create_index("idx_pbp_receiver_season", "play_by_play", ["receiver_player_id", "season"])

    # odds_snapshots (append-only, timestamped — CLV-ready per DATA-03)
    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("game_id", sa.String(20), sa.ForeignKey("games.game_id")),
        sa.Column("sportsbook", sa.String(50), nullable=False),
        sa.Column("market_type", sa.String(30), nullable=False),
        sa.Column("line", sa.Numeric(6, 2)),
        sa.Column("price", sa.SmallInteger()),       # American odds e.g. -110
        sa.Column("snapped_at", sa.TIMESTAMPTZ(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_odds_game_market", "odds_snapshots", ["game_id", "market_type"])
    op.create_index(
        "idx_odds_snapped_at", "odds_snapshots", ["snapped_at"],
        postgresql_ops={"snapped_at": "DESC"}
    )
```

### Pattern 2: nflreadpy Year-by-Year Ingestion Loop (Memory Safe)

**What:** Load one season at a time, select only whitelisted columns, write to PostgreSQL with `ON CONFLICT DO NOTHING`, then explicitly free memory.

**When to use:** Always. Never pass a list of multiple years to `load_pbp()` in a single call without selecting columns first — the full PBP schema is 372+ columns × 50,000+ rows per season.

**Example:**

```python
# src/sportsbet/ingestion/pbp.py

import gc
import psutil
import structlog
import polars as pl
import nflreadpy as nfl
from sqlalchemy import text

log = structlog.get_logger()

# Column whitelist — include only what quant agents query
PBP_COLUMNS = [
    "game_id", "play_id", "season", "week", "posteam", "defteam",
    "play_type", "yards_gained", "down", "ydstogo",
    "passer_player_id", "receiver_player_id", "rusher_player_id",
    "pass_touchdown", "rush_touchdown", "interception", "epa", "wp",
]

def ingest_pbp_seasons(seasons: list[int], engine) -> None:
    """Load PBP data year-by-year with memory guards."""
    for season in seasons:
        mem_before = psutil.virtual_memory().percent
        log.info("pbp_load_start", season=season, memory_pct=mem_before)

        if mem_before > 80:
            log.warning("memory_guard_abort", season=season, memory_pct=mem_before)
            raise MemoryError(f"Memory at {mem_before}% before loading season {season}")

        # Load single season — Polars DataFrame
        df: pl.DataFrame = nfl.load_pbp([season])

        # Select only whitelisted columns that exist in this season's data
        available = [c for c in PBP_COLUMNS if c in df.columns]
        df = df.select(available)

        # Convert to pandas for SQLAlchemy to_sql
        df_pd = df.to_pandas()

        # Chunked write with append + deduplication via DB constraint
        df_pd.to_sql(
            "play_by_play",
            engine,
            if_exists="append",
            index=False,
            chunksize=1000,
            method="multi",
        )

        mem_after = psutil.virtual_memory().percent
        log.info("pbp_load_done", season=season, rows=len(df_pd), memory_pct=mem_after)

        # Free memory before next season
        del df, df_pd
        gc.collect()
```

**Note:** The `UniqueConstraint("game_id", "play_id")` on `play_by_play` makes the DB silently reject duplicates on re-runs. This prevents the `to_sql` replace vs. append bug (Pitfall 12).

### Pattern 3: nflreadpy NGS Ingestion (Three Stat Types)

**What:** NGS data requires three separate calls (stat_type="passing", "receiving", "rushing") because nflreadpy separates them. Each returns a Polars DataFrame.

**When to use:** During Phase 1 setup, load 2016+ NGS data (earliest available) into `ngs_stats`.

**Example:**

```python
# src/sportsbet/ingestion/ngs.py

import nflreadpy as nfl
import polars as pl

NGS_PASSING_COLUMNS = [
    "season", "week", "player_gsis_id", "team_abbr", "player_position",
    "avg_time_to_throw", "avg_completed_air_yards", "avg_intended_air_yards",
    "aggressiveness", "passer_rating", "attempts",
]

NGS_RECEIVING_COLUMNS = [
    "season", "week", "player_gsis_id", "team_abbr", "player_position",
    "avg_separation", "avg_cushion", "avg_yac", "avg_yac_above_expectation",
    "catch_percentage", "targets", "receptions",
]

NGS_RUSHING_COLUMNS = [
    "season", "week", "player_gsis_id", "team_abbr", "player_position",
    "efficiency", "percent_attempts_gte_eight_defenders",
    "rush_yards_over_expected", "avg_time_to_los", "rush_attempts",
]

def ingest_ngs_seasons(seasons: list[int], engine) -> None:
    for stat_type, columns in [
        ("passing", NGS_PASSING_COLUMNS),
        ("receiving", NGS_RECEIVING_COLUMNS),
        ("rushing", NGS_RUSHING_COLUMNS),
    ]:
        for season in seasons:
            df: pl.DataFrame = nfl.load_nextgen_stats([season], stat_type=stat_type)
            available = [c for c in columns if c in df.columns]
            df = df.select(available)
            df.to_pandas().to_sql(
                "ngs_stats", engine,
                if_exists="append", index=False, chunksize=1000,
            )
            del df
            gc.collect()
```

### Pattern 4: odds_snapshots CLV-Ready Schema

**What:** The `odds_snapshots` table is append-only. Every odds fetch writes a timestamped row. CLV is computed later by comparing `price` at `snapped_at` time against the final closing line snapshot.

**When to use:** Write every odds snapshot row at ingestion time. Never update/upsert — always append. Query closing line by finding the snapshot with the latest `snapped_at` before game kickoff.

**Example query for CLV:**

```sql
-- Get closing line for a specific game/market (latest snapshot before kickoff)
SELECT price, snapped_at
FROM odds_snapshots
WHERE game_id = $1 AND market_type = $2 AND sportsbook = $3
ORDER BY snapped_at DESC
LIMIT 1;
```

### Pattern 5: Alembic Configuration with pydantic-settings

**What:** Use pydantic-settings to load `DATABASE_URL` from the environment and pass it to Alembic's `env.py`, avoiding hardcoded connection strings.

**Example:**

```python
# src/sportsbet/config.py
# Pydantic v2 ONLY — do NOT use class Config: (pydantic v1 pattern)
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/sportsbet"
    database_url_async: str = "postgresql+asyncpg://localhost/sportsbet"

settings = Settings()
```

```python
# alembic/env.py (key section)
from sportsbet.config import settings

config.set_main_option("sqlalchemy.url", settings.database_url)
```

### Pattern 6: current_nfl_season() Utility

**What:** A utility function that returns the correct NFL season year based on the NFL calendar. The NFL season starts in September — from February through August, the "current season" is the previous calendar year.

**When to use:** Everywhere a season year is needed. Never use `datetime.now().year` directly (Pitfall 14).

**Example:**

```python
# src/sportsbet/utils.py
from datetime import date

def current_nfl_season() -> int:
    """Return the current NFL season year (season starts September)."""
    today = date.today()
    # NFL season year = calendar year of season start (September)
    # If before September, we're in the off-season of the prior year's season
    if today.month >= 9:
        return today.year
    else:
        return today.year - 1
```

### Anti-Patterns to Avoid

- **Loading all seasons at once:** `nfl.load_pbp([2019, 2020, 2021, 2022, 2023])` loads all into RAM simultaneously. Always loop year-by-year.
- **`if_exists='replace'` on any table:** Drops and recreates the table — destroys previously loaded data. Always use `'append'`.
- **No column whitelist before SQL write:** nflreadpy PBP returns 370+ columns; writing all of them to Postgres wastes disk and slows queries. Always select before write.
- **Hardcoded season constants:** `WHERE season = 2023` becomes stale. Use `current_nfl_season()` or parameterize.
- **Indexes added after data load:** Building an index on a 250k-row table after load works but takes 10-30 seconds and requires a table lock. Define indexes in the migration, before `ingest_pbp_seasons()` is called.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema migrations | Custom migration scripts | Alembic | Version control, rollback, autogenerate diff against SQLAlchemy models |
| NFL data download | Web scraper against nfl.com | nflreadpy | Covers 1999+, all official data, handles S3 parquet download, caching |
| PBP column selection | Manual pandas column list | nflreadpy column whitelist + Polars `.select()` | Arrow-native column pruning at parse time is cheaper than post-load drop |
| DB duplicate prevention | Python dedup logic | PostgreSQL `UniqueConstraint` + `ON CONFLICT DO NOTHING` | DB-enforced constraint is atomic; Python dedup has race conditions |
| Memory monitoring | OS-level check | `psutil.virtual_memory().percent` | Cross-platform, accurate, one line |
| Env var loading | `os.environ.get()` calls | `pydantic-settings BaseSettings` | Type-validated, `.env` support, raises on missing required vars at startup |

**Key insight:** nflreadpy and Alembic together eliminate all the "plumbing" for Phase 1. The only custom code needed is the year-by-year ingestion loop (column whitelist, gc.collect) and the schema DDL.

---

## Common Pitfalls

### Pitfall 1: Using nfl_data_py (Archived)

**What goes wrong:** Installing `nfl-data-py` and calling `import_pbp_data()` — the package is archived (Sep 25, 2025), no security patches, and future nflverse data format changes will break it silently.
**Why it happens:** The REQUIREMENTS.md mentions `nfl_data_py` by name; easy to install the old package.
**How to avoid:** Install `nflreadpy` (not `nfl-data-py`). The function is `nfl.load_pbp([season])` not `import_pbp_data([season])`.
**Warning signs:** `pip show nfl-data-py` succeeds instead of `nflreadpy`.

### Pitfall 2: nflreadpy Returns Polars, Not pandas

**What goes wrong:** Code calls `.column_name` or `df[['col']]` using pandas syntax on a Polars DataFrame — raises `AttributeError` or wrong behavior.
**Why it happens:** Prior nfl_data_py returned pandas; nflreadpy returns Polars by default.
**How to avoid:** Use Polars API (`.select()`, `.filter()`) or call `.to_pandas()` explicitly before pandas operations. For `to_sql()` writes, convert with `.to_pandas()`.
**Warning signs:** `TypeError: 'DataFrame' object is not subscriptable` on multi-column selection.

### Pitfall 3: OOM on Multi-Season Load (Pitfall 4 from PITFALLS.md)

**What goes wrong:** `nfl.load_pbp([2019, 2020, 2021, 2022, 2023])` loads ~5 seasons into RAM; even with Polars' ~40% memory savings over pandas, this is 2-4 GB before column selection.
**Why it happens:** The API accepts a list — ergonomic but memory-unsafe without column selection first.
**How to avoid:** Loop season-by-season. Select whitelisted columns immediately via `.select(available_cols)`. Call `del df; gc.collect()` after each write. Log memory with psutil.
**Warning signs:** Python process is killed by OS without an exception (OOM kill in system log). `load_pbp()` hangs >120 seconds.

### Pitfall 4: Missing Composite Indexes (Pitfall 7 from PITFALLS.md)

**What goes wrong:** Tables created with only a primary key index. Quant agent queries like `WHERE season = 2023 AND posteam = 'KC' AND play_type = 'pass'` do full table scans on 250k+ rows.
**Why it happens:** Alembic auto-generate only creates index for primary key and explicit UniqueConstraints.
**How to avoid:** Explicitly call `op.create_index()` for all composite indexes in the migration file before running ingestion. Required: `(season, week)`, `(posteam, season)`, `(defteam, season)`, `(play_type, season, week)`, `(passer_player_id, season)`, `(receiver_player_id, season)`.
**Warning signs:** `EXPLAIN ANALYZE` on a `season/posteam/play_type` filter shows `Seq Scan` on `play_by_play`.

### Pitfall 5: to_sql `if_exists='replace'` Destroys Data (Pitfall 12 from PITFALLS.md)

**What goes wrong:** Re-running the ingestion script drops and recreates the table, deleting previously loaded seasons.
**Why it happens:** `'replace'` is the most visible option and seems "safe" during development.
**How to avoid:** Always use `if_exists='append'`. Enforce a `UniqueConstraint("game_id", "play_id")` on `play_by_play` so the DB rejects duplicate rows rather than erroring.
**Warning signs:** Running ingestion twice results in a table that has fewer rows than expected, or the table structure is recreated with missing indexes.

### Pitfall 6: NGS Data Only Available from 2016

**What goes wrong:** Calling `nfl.load_nextgen_stats([2010])` returns no data or errors silently — NGS coverage starts in 2016.
**Why it happens:** PBP data goes back to 1999; developers assume NGS has the same range.
**How to avoid:** Hard-code `NGS_MIN_SEASON = 2016` in the ingestion script. Assert `season >= NGS_MIN_SEASON` before any NGS load.
**Warning signs:** Empty DataFrame returned for pre-2016 NGS queries without an exception.

### Pitfall 7: Pydantic v1 Syntax on Any Model (Pitfall 5 from PITFALLS.md)

**What goes wrong:** Using `@validator` or `@root_validator` from pydantic v1 compatibility shim. Validators silently skip edge cases.
**Why it happens:** Old documentation and StackOverflow answers still show v1 patterns.
**How to avoid:** Never import `validator` or `root_validator`. Use only `@field_validator` with `@classmethod`, `@model_validator(mode='before'|'after')`. Set `model_config = ConfigDict(strict=True)` on all models.
**Warning signs:** `from pydantic import validator` does not raise an ImportError (v1 shim active).

---

## Code Examples

Verified patterns from official sources and confirmed API:

### Alembic Init Flow

```bash
# Source: Alembic official docs
alembic init alembic
# Edit alembic/env.py to load DATABASE_URL from pydantic-settings
# Edit alembic.ini: sqlalchemy.url = (set dynamically in env.py)
alembic revision --autogenerate -m "initial_schema"
# Review and add composite indexes manually to the generated migration
alembic upgrade head
```

### nflreadpy Load API

```python
# Source: nflreadpy v0.1.5 official docs (nflreadpy.nflverse.com)
import nflreadpy as nfl

# Load single season PBP (Polars DataFrame)
pbp = nfl.load_pbp([2023])

# Load NGS data by stat type
ngs_passing = nfl.load_nextgen_stats([2023], stat_type="passing")
ngs_receiving = nfl.load_nextgen_stats([2023], stat_type="receiving")
ngs_rushing = nfl.load_nextgen_stats([2023], stat_type="rushing")

# Load player stats
player_stats = nfl.load_player_stats([2023])

# Load schedules (for games table)
schedules = nfl.load_schedules([2023])

# Load injuries (for injury_reports table)
injuries = nfl.load_injuries([2023])

# Polars -> pandas for SQLAlchemy to_sql
pbp_pd = pbp.select(PBP_COLUMNS).to_pandas()

# Get current season utility (built into nflreadpy)
current_season = nfl.get_current_season()
current_week = nfl.get_current_week()
```

### asyncpg Connection Pool

```python
# Source: asyncpg official docs
import asyncpg

async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )

# Usage in quant agent (Phase 3+)
async def query_play_by_play(pool: asyncpg.Pool, season: int, posteam: str) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM play_by_play WHERE season = $1 AND posteam = $2",
            season, posteam
        )
```

### Pydantic v2 Settings Pattern

```python
# Source: pydantic-settings official docs
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    database_url_async: str
    postgres_db: str = "sportsbet"
    log_level: str = "INFO"

settings = Settings()
```

---

## NGS Field Availability

**Confidence: HIGH** (verified via nflreadr data dictionary)

| Field | Stat Type | Available Since | Notes |
|-------|-----------|----------------|-------|
| `avg_time_to_throw` | passing | 2016 | QB-level weekly aggregate |
| `avg_completed_air_yards` | passing | 2016 | |
| `aggressiveness` | passing | 2016 | % passes into tight windows |
| `avg_separation` | receiving | 2016 | Yards of separation at catch/incompletion |
| `avg_cushion` | receiving | 2016 | Pre-snap alignment distance |
| `avg_yac_above_expectation` | receiving | 2016 | |
| `efficiency` | rushing | 2016 | |
| `percent_attempts_gte_eight_defenders` | rushing | 2016 | Stacked box rate |
| `avg_time_to_los` | rushing | 2016 | Time to line of scrimmage |

**Important:** No dedicated `press_man_coverage_rate` field exists in nflreadpy NGS data. The KINE-01/KINE-02 requirements reference "press-man coverage rate" — this will need to be either computed from FTN charting data (`load_ftn_charting()`, available 2022+) or sourced from PFF data (requires separate subscription). This is a Phase 6 concern, but the schema should reserve a nullable column for it in `ngs_stats`.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `nfl_data_py` | `nflreadpy` | September 2025 | Function names changed; returns Polars not pandas |
| `import_pbp_data([seasons])` | `nfl.load_pbp([seasons])` | September 2025 | Same year-list API, different function |
| pandas DataFrames from nflverse | Polars DataFrames | September 2025 | Better memory; need `.to_pandas()` for SQLAlchemy |
| `psycopg2` | `psycopg[binary]` v3 | 2023 | Official successor; sync driver for bulk writes |

**Deprecated/outdated:**
- `nfl_data_py` / `nfl-data-py`: Archived September 25, 2025 — do not install
- `import_pbp_data()`, `import_ngs_data()`, `import_players()`: These functions no longer exist in the maintained package
- `psycopg2`: Sync-only, maintenance mode — use psycopg v3 for sync, asyncpg for async

---

## Open Questions

1. **press_man_coverage_rate for Phase 6**
   - What we know: NGS data from nflreadpy does not include a press-coverage-rate field
   - What's unclear: Whether FTN charting (`load_ftn_charting()`, 2022+) includes coverage type per play at the level needed for KINE-01/KINE-02
   - Recommendation: For Phase 1, add a nullable `press_man_rate NUMERIC(5,2)` column to `ngs_stats` so the schema is forward-compatible. Defer the data source question to Phase 6 research.

2. **nflreadpy caching behavior with year-by-year loop**
   - What we know: nflreadpy has a caching layer (memory or filesystem) that stores downloaded parquet files
   - What's unclear: Whether filesystem caching prevents re-downloading on reruns vs. requiring explicit `clear_cache()`
   - Recommendation: Use `cache_mode="filesystem"` in nflreadpy config for ingestion runs. Test that re-running the ingestion script with `if_exists='append'` + `ON CONFLICT DO NOTHING` is idempotent.

3. **PostgreSQL version requirement**
   - What we know: JSONB (for `weather_json`), `TIMESTAMPTZ`, and composite indexes are all available in PostgreSQL 12+
   - What's unclear: Whether the developer is using Supabase (managed) or local PostgreSQL
   - Recommendation: Target PostgreSQL 15+ for best JSONB performance and access to newer index types. Document minimum version requirement in README.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest >= 8.2 + pytest-asyncio >= 0.23 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — Wave 0 gap |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | `play_by_play` table exists with composite indexes; `SELECT COUNT(*) WHERE season=2023` returns non-zero | integration | `pytest tests/test_schema.py::test_pbp_indexes -x` | Wave 0 |
| DATA-01 | `EXPLAIN ANALYZE` on season/posteam/play_type filter uses Index Scan, not Seq Scan | integration | `pytest tests/test_schema.py::test_explain_no_seq_scan -x` | Wave 0 |
| DATA-02 | Ingestion loop loads 5+ seasons without OOM; `gc.collect()` called between seasons | integration | `pytest tests/test_ingestion.py::test_pbp_multiseason_load -x` | Wave 0 |
| DATA-02 | Column whitelist drops unrequested columns before write | unit | `pytest tests/test_ingestion.py::test_pbp_column_whitelist -x` | Wave 0 |
| DATA-03 | `odds_snapshots` accepts a row and returns it with correct `snapped_at` timestamp | integration | `pytest tests/test_schema.py::test_odds_snapshot_write_read -x` | Wave 0 |
| DATA-04 | `alembic upgrade head` runs cleanly on a fresh PostgreSQL instance | integration | `pytest tests/test_migrations.py::test_alembic_upgrade_clean -x` | Wave 0 |
| DATA-04 | `alembic downgrade base` cleanly removes all tables | integration | `pytest tests/test_migrations.py::test_alembic_downgrade_clean -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/ -x -q --tb=short`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/conftest.py` — shared fixtures: ephemeral PostgreSQL instance (pytest-postgresql), SQLAlchemy engine, asyncpg pool
- [ ] `tests/test_schema.py` — covers DATA-01, DATA-03: table existence, index existence, EXPLAIN ANALYZE assertion, odds_snapshot read/write
- [ ] `tests/test_migrations.py` — covers DATA-04: alembic upgrade head + downgrade base on fresh DB
- [ ] `tests/test_ingestion.py` — covers DATA-02: column whitelist, year-by-year loop (can use 1-2 seasons for speed), gc.collect() call verification
- [ ] Framework install: `uv add --dev pytest pytest-asyncio pytest-postgresql`
- [ ] `pyproject.toml` with `[tool.pytest.ini_options]` `asyncio_mode = "auto"`

---

## Sources

### Primary (HIGH confidence)

- nflreadpy GitHub (https://github.com/nflverse/nflreadpy) — archived status of nfl_data_py confirmed, nflreadpy v0.1.5 current, function API confirmed
- nflreadpy official docs (https://nflreadpy.nflverse.com/api/load_functions/) — `load_pbp()`, `load_nextgen_stats()` parameter specs and return types
- nflreadr NGS data dictionary (https://cran.r-project.org/web/packages/nflreadr/vignettes/dictionary_nextgen_stats.html) — NGS field names for passing/receiving/rushing
- Project ARCHITECTURE.md — PostgreSQL DDL, composite index requirements, odds_snapshots schema
- Project PITFALLS.md — OOM prevention (Pitfall 4), missing indexes (Pitfall 7), to_sql replace bug (Pitfall 12), Pydantic v1 shim (Pitfall 5), hardcoded season (Pitfall 14)
- Alembic official docs (https://alembic.sqlalchemy.org/en/latest/) — op.create_index, env.py patterns

### Secondary (MEDIUM confidence)

- Alembic changelog (https://alembic.sqlalchemy.org/en/latest/changelog.html) — v1.13+ current feature set
- asyncpg official docs — connection pool patterns; https://magicstack.github.io/asyncpg/
- pydantic-settings official docs — BaseSettings patterns; https://docs.pydantic.dev/latest/

### Tertiary (LOW confidence)

- nflreadpy caching behavior — documented at library level but specific behavior of filesystem cache with `if_exists='append'` loop not verified by test

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — nflreadpy/Polars/Alembic/asyncpg all verified against official sources
- Architecture: HIGH — PostgreSQL DDL patterns are standard; Alembic migration patterns verified
- nflreadpy API: HIGH — verified against official docs and GitHub; function signatures confirmed
- NGS field availability: HIGH — verified against nflreadr official data dictionary
- nfl_data_py deprecation: HIGH — confirmed via GitHub WebFetch: archived Sep 25, 2025
- Pitfalls: HIGH — OOM/index/to_sql patterns are well-documented; Polars-specific OOM behavior is MEDIUM

**Research date:** 2026-03-10
**Valid until:** 2026-06-10 (90 days — nflreadpy is actively maintained; Alembic/PostgreSQL patterns are stable)
