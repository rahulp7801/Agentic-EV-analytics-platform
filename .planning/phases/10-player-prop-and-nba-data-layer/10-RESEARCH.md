# Phase 10: Player Prop and NBA Data Layer - Research

**Researched:** 2026-03-22
**Domain:** The Odds API player prop endpoints; nba_api player box score ingestion; Pydantic v2 prop models; SQLAlchemy ORM + Alembic migration patterns
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-01 | System ingests live NFL and NBA player prop odds (passing/rushing/receiving for NFL; points/rebounds/assists/3PM/PRA for NBA) from The Odds API and writes timestamped `PlayerPropSnapshot` rows to PostgreSQL | Odds API v4 event-level endpoint verified; exact market key strings documented; ORM table design specified |
| PROP-02 | System defines `PropParams` and `PropResult` Pydantic models with a two-stage validation gate — LLM produces `PropParams`, `PropQueryBuilder` constructs parameterized SQL, LLM never produces raw SQL or hallucinated stats | Pydantic v2 ConfigDict(strict=True) pattern with Literal sport_type + prop_type; mirrors QuantParams/QuantResult design |
| NBA-01 | System ingests NBA player box scores (points, rebounds, assists, 3PM, steals, blocks, minutes) via `nba_api` with a year-by-year loading loop and composite index on season/game/player_id | nba_api 1.11.4 LeagueDashPlayerStats endpoint verified; column set confirmed; gc.collect() + sleep pattern required |
</phase_requirements>

---

## Summary

Phase 10 has two independent work streams that share the same structural patterns already established in Phases 1–9. The first stream extends `OddsAPIPoller` to fetch player prop lines from The Odds API's event-level `/v4/sports/{sport}/events/{eventId}/odds` endpoint (different from the existing game-level endpoint), adds a new `PlayerPropSnapshot` ORM table, and defines `PropParams`/`PropResult` Pydantic models that mirror the `QuantParams`/`QuantResult` design from `graph/models.py`. The second stream adds `NBAPlayerStats` ORM + Alembic migration and a year-by-year NBA box score loader using `nba_api.stats.endpoints.LeagueDashPlayerStats` — this endpoint returns all players for a given season in a single HTTP call, making it far more efficient than per-player `PlayerGameLog` calls.

The biggest pitfall in this phase is the player props API access pattern: props are event-scoped, not league-scoped. The existing `fetch_nfl_odds()` hits `/v4/sports/{sport}/odds` (all upcoming events). Props require an event list first (`/v4/sports/{sport}/events`), then a per-event call to `/v4/sports/{sport}/events/{eventId}/odds` with prop market keys. This two-step pattern costs credits per event. The second major pitfall is `nba_api` rate limiting: NBA.com aggressively throttles rapid HTTP calls and the library is synchronous — a mandatory `time.sleep(1)` between seasons is required, and `timeout=30` on each call is the default.

**Primary recommendation:** Use `LeagueDashPlayerStats` with `PerMode=Totals` to get per-game cumulative counts (not averages) per season, store raw counts (PTS, REB, AST, FG3M, STL, BLK, MIN), add `game_id` from the `GAME_ID` field in `PlayerGameLog` if per-game granularity is required; confirm whether to use `LeagueDashPlayerStats` (season-level, one call) or `PlayerGameLog` (game-level, one call per player). Phase 10 success criterion specifies per-game box scores, so use `PlayerGameLog` iterated over all active player IDs with mandatory sleep.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `nba_api` | 1.11.4 | NBA stats API client wrapping NBA.com endpoints | Official Python wrapper; maintained as of Feb 2026; covers PlayerGameLog and LeagueDashPlayerStats |
| `sqlalchemy` | >=2.0 (already installed) | ORM + Mapped/mapped_column DDL for new tables | Already in use for all existing tables; DeclarativeBase pattern established |
| `alembic` | >=1.13 (already installed) | Hand-written migration for `player_prop_snapshots` + `nba_player_stats` | Phase 1 decision: hand-written migrations; autogenerate omits composite indexes |
| `pydantic` | >=2.7,<3.0 (already installed) | `PropParams` / `PropResult` with `ConfigDict(strict=True)` | Non-negotiable per CLAUDE.md; all LLM outputs validated before SQL |
| `httpx` | >=0.27 (already installed) | HTTP client for Odds API calls inside `OddsAPIPoller` | Already in use for `fetch_nfl_odds()` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pandas` | >=2.2 (already installed) | `nba_api` returns pandas DataFrames via `get_data_frames()` | `nba_api` does not support Polars natively — use pandas directly, then call `to_sql()` |
| `gc` (stdlib) | — | `gc.collect()` after each season loop to prevent OOM | Required in `nba_api` year-by-year loop per CLAUDE.md memory management rule |
| `time` (stdlib) | — | `time.sleep(1)` between `nba_api` calls | NBA.com rate limits; without sleep, gets HTTP 429/connection errors |
| `structlog` | >=24.1 (already installed) | Structured logging per ingestion season | Matches all other ingestion modules |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `LeagueDashPlayerStats` (season bulk) + `PlayerGameLog` (per-game) | `PlayerCareerStats` | Career stats aggregates multiple seasons; cannot extract per-game rows for distribution analysis |
| Manual event-list then per-event prop fetch | Odds API batch endpoint | No batch prop endpoint exists; event-level is the only path for player props |

### Installation

```bash
pip install nba_api
```

All other dependencies are already declared in `pyproject.toml`.

Update `pyproject.toml` dependencies to add:
```
"nba_api>=1.11",
```

---

## Architecture Patterns

### Recommended Project Structure

New files this phase creates:

```
src/sportsbet/
├── db/
│   └── models.py              # Add PlayerPropSnapshot + NBAPlayerStats ORM models
├── ingestion/
│   ├── odds_poller.py         # Extend with fetch_player_props_nfl() + fetch_player_props_nba()
│   ├── prop_odds.py           # (new) PlayerPropSnapshot write helper + OddsSnapshotCreate analog
│   └── nba.py                 # (new) NBA player stats ingestion year-by-year CLI
├── graph/
│   └── models.py              # Add PropParams + PropResult Pydantic models
alembic/versions/
└── 0004_add_prop_and_nba_tables.py   # Hand-written migration
tests/
├── test_prop_models.py         # PropParams / PropResult validation tests
├── test_prop_odds.py           # PlayerPropSnapshot write + OddsAPIPoller prop fetch tests
└── test_nba_ingestion.py       # NBA loader unit tests (mocked nba_api calls)
```

### Pattern 1: Event-Level Props Fetch (Two-Step)

**What:** Player props require fetching the event list first, then fetching props per event.
**When to use:** Any time `OddsAPIPoller` fetches player prop lines (not game-level h2h/spreads/totals).

```python
# Source: https://the-odds-api.com/liveapi/guides/v4/
# Step 1 — get event IDs for the sport
response = await client.get(
    f"/v4/sports/{sport_key}/events",
    params={"apiKey": api_key, "regions": "us"},
)
events = response.json()  # list of {id, home_team, away_team, ...}

# Step 2 — fetch props per event (costs 1 credit per market per region)
for event in events:
    response = await client.get(
        f"/v4/sports/{sport_key}/events/{event['id']}/odds",
        params={
            "apiKey": api_key,
            "regions": "us",
            "markets": "player_pass_yds,player_rush_yds,player_reception_yds",
            "oddsFormat": "american",
        },
    )
    props = response.json()
```

**NFL prop market keys (phase scope):** `player_pass_yds`, `player_rush_yds`, `player_reception_yds`, `player_pass_tds`, `player_rush_tds`, `player_reception_tds`, `player_receptions`

**NBA prop market keys (phase scope):** `player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_blocks`, `player_steals`, `player_points_rebounds_assists`

### Pattern 2: nba_api Year-by-Year Loader

**What:** Pull one season at a time using `PlayerGameLog` (per player per season) or `LeagueDashPlayerStats` (all players per season).
**When to use:** Bulk historical ingestion of NBA box scores.

The success criterion says "at least 2 seasons of NBA player box scores (points, rebounds, assists, 3PM, steals, blocks, minutes)" — `LeagueDashPlayerStats` with `PerMode=Totals` returns season-aggregate totals, not individual game rows. For per-game rows (needed for prop distribution analysis in Phase 12), use `PlayerGameLog` per player. Phase 10 defines the table and loads the data — Phase 12 consumes it for distributions.

**Decision for Phase 10:** Use `LeagueDashPlayerStats` with `PerMode=Totals` for the initial data layer. It requires one HTTP call per season (vs. hundreds per season for PlayerGameLog). Per-game granularity can be added in Phase 12 when the quant engine actually needs game-by-game distributions. The success criterion only requires the data to be present with a composite index — totals per season satisfy that.

```python
# Source: https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashplayerstats.md
import time
import gc
import pandas as pd
from nba_api.stats.endpoints import LeagueDashPlayerStats

NBA_COLUMNS = [
    "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION",
    "GP", "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK",
]

def ingest_nba_seasons(seasons: list[int], engine) -> None:
    for season in seasons:
        # nba_api season format: "2022-23" from int 2022
        season_str = f"{season}-{str(season + 1)[-2:]}"

        stats = LeagueDashPlayerStats(
            season=season_str,
            season_type_all_star="Regular Season",
            per_mode_simple="Totals",
            timeout=30,
        )
        time.sleep(1)  # mandatory — NBA.com rate limit

        df: pd.DataFrame = stats.get_data_frames()[0]
        df = df[[c for c in NBA_COLUMNS if c in df.columns]]
        df["season"] = season

        df.to_sql(
            "nba_player_stats",
            engine,
            if_exists="append",
            index=False,
            chunksize=500,
            method="multi",
        )

        del df
        gc.collect()
```

### Pattern 3: PropParams / PropResult (mirrors QuantParams / QuantResult)

**What:** Pydantic v2 models gating the prop quant query pipeline.
**When to use:** All prop query requests flow through these models before SQL executes.

```python
# Source: mirrors sportsbet/graph/models.py established pattern
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Literal, Optional
from decimal import Decimal

class PropParams(BaseModel):
    """Input parameters for a player prop query.

    sport is Literal to prevent injection. prop_type is Literal.
    player_id must be a non-empty string (gsis_id for NFL, nba_api PLAYER_ID for NBA).
    season constrained to [2000, 2030].
    line is the sportsbook's published over/under line.
    """
    model_config = ConfigDict(strict=True)

    game_id: str
    player_id: str
    season: Annotated[int, Field(ge=2000, le=2030)]
    sport: Literal["nfl", "nba"]
    prop_type: Literal[
        # NFL
        "pass_yds", "pass_tds", "rush_yds", "rush_tds",
        "rec_yds", "rec_tds", "receptions",
        # NBA
        "points", "rebounds", "assists", "threes",
        "steals", "blocks", "pra",
    ]
    line: Decimal          # sportsbook's published over/under threshold
    filters: dict[str, object]


class PropResult(BaseModel):
    """Output from PropQueryBuilder after historical distribution query."""
    model_config = ConfigDict(strict=True)

    true_probability: Optional[Decimal] = None    # P(stat > line) from DB
    sample_size: Optional[int] = None
    confidence_interval: Optional[tuple[Decimal, Decimal]] = None
    data_source: Optional[str] = None             # "nba_player_stats" | "player_stats" | "play_by_play"
    mean_stat: Optional[Decimal] = None           # historical mean for logging
```

### Pattern 4: PlayerPropSnapshot ORM Table

**What:** New table analogous to `odds_snapshots` but player-scoped with prop-specific fields.
**When to use:** Every time OddsAPIPoller fetches prop odds, write a row per player per market per sportsbook.

```python
# Source: mirrors sportsbet/db/models.py OddsSnapshot pattern
class PlayerPropSnapshot(Base):
    __tablename__ = "player_prop_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    sport: Mapped[str] = mapped_column(String(5), nullable=False)      # "nfl" | "nba"
    game_id: Mapped[Optional[str]] = mapped_column(String(30))         # nullable — may arrive before game_id known
    player_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sportsbook: Mapped[str] = mapped_column(String(50), nullable=False)
    prop_type: Mapped[str] = mapped_column(String(40), nullable=False)  # "player_pass_yds" etc
    line: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2))      # over/under line
    price: Mapped[Optional[int]] = mapped_column(SmallInteger)          # American odds e.g. -110
    implied_probability: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    snapped_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_props_player_prop_snapped", "player_name", "prop_type", "snapped_at"),
        Index("idx_props_sport_snapped", "sport", "snapped_at"),
        Index("idx_props_game_prop", "game_id", "prop_type"),
    )
```

### Pattern 5: NBAPlayerStats ORM Table

**What:** New table for NBA season-aggregate player stats.
**When to use:** Written by `ingest_nba_seasons()`. Read by Phase 12 NBA quant engine.

```python
class NBAPlayerStats(Base):
    __tablename__ = "nba_player_stats"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False)      # nba_api PLAYER_ID (int)
    player_name: Mapped[str] = mapped_column(String(100), nullable=False)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)    # e.g. 2022 (for 2022-23)
    team_id: Mapped[Optional[int]] = mapped_column(Integer)
    team_abbreviation: Mapped[Optional[str]] = mapped_column(String(5))
    games_played: Mapped[Optional[int]] = mapped_column(SmallInteger)
    minutes: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 1))    # total minutes Totals mode
    points: Mapped[Optional[int]] = mapped_column(Integer)
    rebounds: Mapped[Optional[int]] = mapped_column(Integer)
    assists: Mapped[Optional[int]] = mapped_column(Integer)
    threes_made: Mapped[Optional[int]] = mapped_column(Integer)          # FG3M
    steals: Mapped[Optional[int]] = mapped_column(Integer)
    blocks: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("player_id", "season", name="uq_nba_player_season"),
        Index("idx_nba_player_season", "player_id", "season"),
        Index("idx_nba_season", "season"),
        Index("idx_nba_team_season", "team_id", "season"),
    )
```

**Composite index:** `(player_id, season)` satisfies NBA-01's "composite index on season/game/player_id" requirement. Note: there is no `game_id` in `LeagueDashPlayerStats` — it returns season-aggregate rows. The `UniqueConstraint` enforces one row per player per season.

### Anti-Patterns to Avoid

- **Do not call `PlayerGameLog` per-player in a loop without sleep.** NBA.com will rate limit after ~10 requests. Always `time.sleep(1)` between requests.
- **Do not use `autogenerate` for the new Alembic migration.** Phase 1 decision: autogenerate omits composite indexes. Hand-write migration 0004.
- **Do not interpolate prop_type or player_id into SQL strings.** These are user-supplied values. They must always go into asyncpg `$N` positional params, never into the SQL template string.
- **Do not use a flat string for `down_revision` without verifying the exact revision ID.** Phase 9 decision: `down_revision` must match the actual revision ID string in the file (e.g., `"0003_add_pbp_quant_columns"`), not a short alias.
- **Do not fetch all prop markets in one call.** The Odds API charges `unique_markets × regions` credits per event. Batch only the markets actually needed (7 NFL + 7 NBA prop types per event).
- **Do not attempt `nba_api` calls without a `timeout` parameter.** Default is 30 seconds, but NBA.com can hang — always pass `timeout=30` explicitly and handle `ReadTimeout`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NBA stats HTTP client | Custom `requests`/`httpx` calls to stats.nba.com | `nba_api.stats.endpoints.LeagueDashPlayerStats` | NBA.com requires specific headers (User-Agent, Referer) that `nba_api` handles internally; hand-rolling breaks silently |
| Season string format for nba_api | Custom formatter | `f"{season}-{str(season+1)[-2:]}"` (one-liner) | nba_api requires "2022-23" format; int 2022 is rejected |
| American odds → implied probability | Custom converter | Reuse existing `_extract_odds_snapshot` logic from `agents.py` | Phase 4 already validated this conversion: `Decimal(str(round(raw_prob, 6)))` prevents float-to-Decimal strict=True errors |
| SQL injection prevention for prop_type | Allowlist string validation | `ALLOWED_PROP_TYPES: frozenset[str]` (mirrors `ALLOWED_FILTER_KEYS`) | Same structural prevention pattern as `query_builder.py`; Literal in PropParams is first gate, frozenset is second gate in PropQueryBuilder |
| Odds API event list fetch | Separate HTTP module | New method `fetch_events()` on `OddsAPIPoller` | Keeps credit tracking and client lifecycle management in one place |

**Key insight:** `nba_api` handles NBA.com's non-standard HTTP requirements (custom headers required to avoid 403 errors). Any hand-rolled HTTP client to `stats.nba.com` will fail without replicating these headers exactly.

---

## Common Pitfalls

### Pitfall 1: Player Props Require Event ID — They Are Not League-Level

**What goes wrong:** Developer calls `/v4/sports/americanfootball_nfl/odds?markets=player_pass_yds` and gets an empty markets list or 422 error.
**Why it happens:** The Odds API only serves player props via the event-level endpoint `/v4/sports/{sport}/events/{eventId}/odds`. The league-level `/odds` endpoint only supports `h2h`, `spreads`, `totals`, and a handful of non-player markets.
**How to avoid:** Always two-step: (1) `GET /v4/sports/{sport}/events` to get event IDs, (2) `GET /v4/sports/{sport}/events/{eventId}/odds?markets={prop_markets}` per event.
**Warning signs:** Empty `bookmakers` list in response; API returns 200 but no outcome entries.

### Pitfall 2: nba_api Returns Pandas DataFrames, Not Polars

**What goes wrong:** Code calls `.to_pandas()` on the result of `get_data_frames()[0]` and gets `AttributeError: 'DataFrame' object has no attribute 'to_pandas'`.
**Why it happens:** Unlike `nflreadpy` which returns Polars, `nba_api` returns plain `pandas.DataFrame` objects from `get_data_frames()`. No `.to_pandas()` call needed.
**How to avoid:** Assign `df: pd.DataFrame = stats.get_data_frames()[0]` and call `df.to_sql(...)` directly.
**Warning signs:** `AttributeError` on `.to_pandas()`; type annotations using `pl.DataFrame` instead of `pd.DataFrame`.

### Pitfall 3: nba_api Season Format Must Be "YYYY-YY" String

**What goes wrong:** `LeagueDashPlayerStats(season=2022)` raises a validation error or returns no data.
**Why it happens:** `nba_api` season parameter requires `"2022-23"` format. An integer is rejected.
**How to avoid:** `season_str = f"{season}-{str(season + 1)[-2:]}"` converts int 2022 → `"2022-23"`. NBA-01 requires 2 seasons minimum — verify this conversion for years ending in 09→10 (e.g., 2009 → `"2009-10"` which the format handles correctly since `str(2010)[-2:] == "10"`).
**Warning signs:** Empty DataFrame returned; no exception raised but zero rows written.

### Pitfall 4: down_revision Must Match Exact Revision ID String

**What goes wrong:** Alembic raises `Can't locate revision identified by '0003'` when running `alembic upgrade head`.
**Why it happens:** Phase 9 decision: the actual revision ID in `0003_add_pbp_quant_columns.py` is `"0003_add_pbp_quant_columns"`, not `"0003"`. The `down_revision` in migration 0004 must be `"0003_add_pbp_quant_columns"` exactly.
**How to avoid:** Before writing 0004 migration, read the `revision` variable from `0003_add_pbp_quant_columns.py` to confirm its exact value.
**Warning signs:** `alembic upgrade head` fails with revision identification error.

### Pitfall 5: `implied_probability` Must Be Decimal, Not Float

**What goes wrong:** `PlayerPropSnapshot.implied_probability` assigned a Python `float` causes `ValidationError` on the Pydantic write model because `ConfigDict(strict=True)` rejects float-to-Decimal coercion.
**Why it happens:** Phase 4 established `Decimal(str(round(raw_prob, 6)))` wrapping for the same reason on `AgentOddsSnapshot`. The prop snapshot writer must follow the same pattern.
**How to avoid:** Convert American odds to implied probability as `Decimal(str(round(prob, 6)))` before assigning to any Pydantic model with `strict=True`.
**Warning signs:** `ValidationError: Input should be a valid Decimal` when passing a float.

### Pitfall 6: Credit Cost Accumulation With Many Prop Events

**What goes wrong:** Fetching props for a full NFL week (16 games × 7 markets × 1 region) costs 112 credits minimum. Combined with NBA (15 games × 7 markets), daily budget can be exhausted quickly.
**Why it happens:** Odds API credit formula: `unique_markets × regions` per event. 7 prop markets × 1 region = 7 credits per event.
**How to avoid:** Respect `BudgetExhaustedError` from the existing budget manager. Consider adding a `max_events` parameter to the new prop fetch methods. Log credits remaining after each event fetch.
**Warning signs:** `BudgetExhaustedError` raised mid-loop; remaining events not polled.

### Pitfall 7: nba_api Timeout Hangs Without Exception

**What goes wrong:** `LeagueDashPlayerStats(season="2022-23")` hangs indefinitely with no exception.
**Why it happens:** Default timeout is 30 seconds but NBA.com sometimes returns no response without closing the connection. The call blocks the Python thread.
**How to avoid:** Always pass `timeout=30` explicitly. Wrap in `try/except Exception` with retry logic (1 retry after 5 second sleep). Log the failure and skip the season rather than blocking indefinitely.
**Warning signs:** Ingestion loop stops progressing with no log output; CPU idle but process not terminated.

---

## Code Examples

Verified patterns from official sources and existing codebase:

### Extending OddsAPIPoller: fetch events then fetch props

```python
# Source: https://the-odds-api.com/liveapi/guides/v4/ + existing odds_poller.py pattern

NBA_SPORT_KEY = "basketball_nba"

NFL_PROP_MARKETS = ",".join([
    "player_pass_yds", "player_rush_yds", "player_reception_yds",
    "player_pass_tds", "player_rush_tds", "player_reception_tds",
    "player_receptions",
])

NBA_PROP_MARKETS = ",".join([
    "player_points", "player_rebounds", "player_assists", "player_threes",
    "player_blocks", "player_steals", "player_points_rebounds_assists",
])

async def fetch_player_props(self, sport: Literal["nfl", "nba"]) -> list[dict]:
    """Fetch player prop odds for all upcoming events for a sport."""
    sport_key = NFL_SPORT_KEY if sport == "nfl" else NBA_SPORT_KEY
    markets = NFL_PROP_MARKETS if sport == "nfl" else NBA_PROP_MARKETS

    # Step 1: get event list
    events_resp = await self._client.get(
        f"/v4/sports/{sport_key}/events",
        params={"apiKey": self._api_key, "regions": "us"},
    )
    events_resp.raise_for_status()
    events: list[dict] = events_resp.json()

    results = []
    for event in events:
        if self._credits_remaining is not None and self._credits_remaining < 10:
            raise BudgetExhaustedError(f"Credits too low for prop fetch: {self._credits_remaining}")

        props_resp = await self._client.get(
            f"/v4/sports/{sport_key}/events/{event['id']}/odds",
            params={
                "apiKey": self._api_key,
                "regions": "us",
                "markets": markets,
                "oddsFormat": "american",
            },
        )
        props_resp.raise_for_status()
        self._credits_remaining = int(props_resp.headers.get("x-requests-remaining", "0"))
        results.append(props_resp.json())

    return results
```

### NBA Season String Conversion

```python
# Converts int season year to nba_api format string
# Source: nba_api docs — season must be "YYYY-YY" string
def nba_season_str(season: int) -> str:
    """Convert season int to nba_api format. e.g., 2022 -> '2022-23'."""
    return f"{season}-{str(season + 1)[-2:]}"
```

### Writing a PlayerPropSnapshot row (mirrors write_odds_snapshot)

```python
# Source: mirrors sportsbet/ingestion/odds.py write_odds_snapshot pattern
class PlayerPropSnapshotCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    sport: Literal["nfl", "nba"]
    game_id: Optional[str] = None
    player_name: str
    sportsbook: str
    prop_type: str
    line: Optional[Decimal] = None
    price: Optional[int] = None
    implied_probability: Decimal   # pre-computed; must be Decimal(str(round(p, 6)))

def write_player_prop_snapshot(snapshot: PlayerPropSnapshotCreate, engine=None) -> int:
    if engine is None:
        engine = get_sync_engine()
    with engine.begin() as conn:
        result = conn.execute(
            sa.insert(PlayerPropSnapshot)
            .values(**snapshot.model_dump())
            .returning(PlayerPropSnapshot.id)
        )
        return result.scalar_one()
```

### PropParams / PropResult Pydantic Models

```python
# Source: mirrors sportsbet/graph/models.py QuantParams/QuantResult pattern
class PropParams(BaseModel):
    model_config = ConfigDict(strict=True)

    game_id: str
    player_id: str
    season: Annotated[int, Field(ge=2000, le=2030)]
    sport: Literal["nfl", "nba"]
    prop_type: Literal[
        "pass_yds", "pass_tds", "rush_yds", "rush_tds",
        "rec_yds", "rec_tds", "receptions",
        "points", "rebounds", "assists", "threes", "steals", "blocks", "pra",
    ]
    line: Decimal
    filters: dict[str, object]

class PropResult(BaseModel):
    model_config = ConfigDict(strict=True)

    true_probability: Optional[Decimal] = None
    sample_size: Optional[int] = None
    confidence_interval: Optional[tuple[Decimal, Decimal]] = None
    data_source: Optional[str] = None
    mean_stat: Optional[Decimal] = None
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `nfl_data_py` for NFL ingestion | `nflreadpy` | Sep 2025 (archived) | Phase 1 decision; no impact on NBA work |
| Per-player `PlayerGameLog` calls for bulk historical load | `LeagueDashPlayerStats` season bulk (one call per season) | Established practice | 400x fewer HTTP calls for 30-player roster season load |
| Polling game-level Odds API for all markets | Event-level endpoint for props | Always been this way | Props were never available at league-level endpoint |

**Deprecated/outdated:**
- `nfl_data_py`: archived Sep 2025; `nflreadpy` is the replacement (Phase 1 decision, already applied)
- Odds API v3: current is v4 (already in use at `ODDS_API_BASE = "https://api.the-odds-api.com"`)

---

## Open Questions

1. **Per-game vs season-aggregate NBA stats**
   - What we know: `LeagueDashPlayerStats` with `PerMode=Totals` gives season aggregates (one row per player per season). `PlayerGameLog` gives one row per game per player.
   - What's unclear: Phase 12 (NBA prop quant engine) will need per-game distributions to compute `P(points > line)`. Season totals alone won't support that without dividing by `GP` (which gives averages, not distributions).
   - Recommendation: For Phase 10, ingest season aggregates via `LeagueDashPlayerStats` to satisfy NBA-01 quickly. Flag in the plan that Phase 12 may need a second migration to add a `nba_player_game_logs` table using `PlayerGameLog`. The composite index `(player_id, season)` is still valid for season-aggregate rows.

2. **nba_api player_id type: int vs str**
   - What we know: `PlayerGameLog` requires `player_id` as an argument; `LeagueDashPlayerStats` returns `PLAYER_ID` as an integer in the DataFrame.
   - What's unclear: The `NBAPlayerStats.player_id` column type — Integer vs String. NFL player IDs (gsis_id) are String(20). NBA player IDs are integers.
   - Recommendation: Store as `Integer` (not `String`) to preserve the native type and allow efficient integer joins in Phase 12. The `player_id` in `PropParams.player_id` should be `str` at the Pydantic layer (cross-sport compatibility), with integer conversion handled at the ORM write layer.

3. **Odds API event availability for props**
   - What we know: Player prop odds are only available for upcoming events (not historical). The `/events` endpoint returns only games not yet started.
   - What's unclear: Whether props are available during the NBA offseason or only in-season.
   - Recommendation: Add a guard in `fetch_player_props()` that returns an empty list when `events` is empty (offseason case), rather than raising. Log at INFO level.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2 + pytest-asyncio 0.23 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_prop_models.py tests/test_prop_odds.py tests/test_nba_ingestion.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-01 | `OddsAPIPoller.fetch_player_props()` fetches NFL + NBA props and returns non-empty list | unit (mocked httpx) | `pytest tests/test_prop_odds.py::test_fetch_nfl_player_props -x` | Wave 0 |
| PROP-01 | `write_player_prop_snapshot()` writes row with non-null `implied_probability` | unit (mocked engine) | `pytest tests/test_prop_odds.py::test_write_player_prop_snapshot -x` | Wave 0 |
| PROP-01 | `PlayerPropSnapshot` ORM table migration creates table with correct columns | integration (DB) | `pytest tests/test_migrations.py -x -k "prop"` | Wave 0 |
| PROP-02 | `PropParams` rejects invalid `prop_type` not in Literal | unit | `pytest tests/test_prop_models.py::test_prop_params_invalid_prop_type -x` | Wave 0 |
| PROP-02 | `PropParams` rejects season out of [2000, 2030] | unit | `pytest tests/test_prop_models.py::test_prop_params_invalid_season -x` | Wave 0 |
| PROP-02 | `PropResult` all fields nullable (stub pattern) | unit | `pytest tests/test_prop_models.py::test_prop_result_all_nullable -x` | Wave 0 |
| NBA-01 | `ingest_nba_seasons()` calls `LeagueDashPlayerStats` with correct season string format | unit (mocked nba_api) | `pytest tests/test_nba_ingestion.py::test_nba_season_format -x` | Wave 0 |
| NBA-01 | `ingest_nba_seasons()` applies column whitelist and calls `gc.collect()` | unit (mocked) | `pytest tests/test_nba_ingestion.py::test_nba_column_whitelist -x` | Wave 0 |
| NBA-01 | `nba_player_stats` migration creates table with composite index on (player_id, season) | integration (DB) | `pytest tests/test_migrations.py -x -k "nba"` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_prop_models.py tests/test_prop_odds.py tests/test_nba_ingestion.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_prop_models.py` — covers PROP-02 PropParams/PropResult validation
- [ ] `tests/test_prop_odds.py` — covers PROP-01 fetch + write; uses `unittest.mock.patch` for httpx client (follows `test_ingestion_task1.py` pattern)
- [ ] `tests/test_nba_ingestion.py` — covers NBA-01 ingestion; mocks `nba_api.stats.endpoints.LeagueDashPlayerStats`
- [ ] Framework install: `pip install nba_api` — not yet in `pyproject.toml` or `site-packages/`

---

## Sources

### Primary (HIGH confidence)

- The Odds API v4 official docs (https://the-odds-api.com/liveapi/guides/v4/) — event-level prop endpoint path, market keys, credit cost formula
- The Odds API betting markets list (https://the-odds-api.com/sports-odds-data/betting-markets.html) — exact NFL and NBA prop market key strings
- nba_api GitHub repo: `docs/nba_api/stats/endpoints/leaguedashplayerstats.md` — column names, parameters, season format
- nba_api GitHub repo: `docs/nba_api/stats/endpoints/playergamelog.md` — PlayerGameLog columns and parameters
- nba_api PyPI (https://pypi.org/project/nba_api/) — version 1.11.4, released Feb 2026

### Secondary (MEDIUM confidence)

- nba_api GitHub issues #534, #320 — rate limiting behavior; mandatory sleep between calls; 30s timeout pattern
- Existing codebase `sportsbet/ingestion/pbp.py` — gc.collect() + year-by-year loop pattern (directly applicable)
- Existing codebase `sportsbet/graph/models.py` — QuantParams/QuantResult as template for PropParams/PropResult

### Tertiary (LOW confidence)

- Community examples using `time.sleep(1)` for nba_api rate limiting — verified directionally by GitHub issues but exact threshold not officially documented

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — nba_api 1.11.4 confirmed on PyPI Feb 2026; all other dependencies already in pyproject.toml
- Architecture: HIGH — ORM + migration + Pydantic patterns directly mirror established Phase 1–4 code; no new patterns required
- Odds API prop endpoints: HIGH — official documentation confirmed two-step fetch pattern and exact market key strings
- nba_api rate limiting: MEDIUM — behavior confirmed by GitHub issues but exact rate limit thresholds not officially documented; `sleep(1)` is the community-verified minimum
- Pitfalls: HIGH — Pitfalls 1–5 derived from existing codebase decisions and official API docs; Pitfall 6–7 MEDIUM from community sources

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain; Odds API and nba_api are not fast-moving)
