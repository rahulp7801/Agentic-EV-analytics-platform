# Phase 20: NBA Context Signals Auto-Population - Research

**Researched:** 2026-03-25
**Domain:** LangGraph node factory, asyncpg queries against nba_player_gamelogs, NBAContextSignals Pydantic model
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-05 | System calculates true probability for NBA player props using pace-adjusted historical distributions with opponent defensive rating, rest days, and home/away context | `_apply_nba_context_adjustments` already implements all four adjustment stages and is invoked by `make_nba_quant_agent`. The gap is that `nba_context_signals` is always `None` in automated runs because no node populates it before the NBA quant agent runs. A `NBAContextSignalsProducer` node wired before `nba_quant_agent` fills this field from `nba_player_gamelogs` data already present in the DB. |
| NBA-02 | System applies pace adjustment, back-to-back rest penalty, and opponent defensive rating weighting to NBA player prop probability distributions | Same root cause as PROP-05. All four adjustment stages are implemented. The pipeline simply never receives non-None `NBAContextSignals` in automated runs. This phase makes the pipeline fully automatic. |
</phase_requirements>

---

## Summary

Phase 20 closes INT-3 from the v1.0 audit: `GraphState.nba_context_signals` is always `None` in automated pipeline runs because no pipeline node ever sets it. The four-stage contextual adjustment pipeline in `nba_agents.py` (`_apply_nba_context_adjustments`) is fully implemented, passes tests, and has correct math — it simply receives `context=None` and returns immediately.

The fix is a single new LangGraph node, `NBAContextSignalsProducer`, implemented as a closure factory (`make_nba_context_signals_producer(pool)`) following the identical factory pattern used by all existing agent nodes in this codebase. The node reads two pieces of data that are already in the database: (1) recent `nba_player_gamelogs` rows for the player's team to detect back-to-back scheduling, and (2) season-aggregate `nba_player_stats` opponent data to derive a proxy `opponent_def_rating`. `is_home` and `rest_days` are derived from the gamelog schema (which stores `is_home` and `game_date` per row). The node writes `{"nba_context_signals": NBAContextSignals(...)}` to state, which `nba_quant_agent` then consumes.

The node must be wired into `graph.py` as a new optional parameter `nba_context_producer_node`, inserted before `nba_quant_agent` in the graph topology. When present, the graph chain becomes: `nba_quant_agent (incoming) -> nba_context_producer -> nba_quant_agent -> prop_arbitrage_agent`. When absent (stub), it returns `{"nba_context_signals": None}` maintaining backward compatibility.

**Primary recommendation:** Implement `NBAContextSignalsProducer` as a closure factory in `src/sportsbet/prop/nba_context_producer.py`. Wire it before `nba_quant_agent` in `graph.py`. Use `nba_player_gamelogs` for back-to-back detection and `is_home` derivation; use `nba_player_stats` season averages as a proxy for opponent defensive rating. No schema migrations required — all needed data is in the existing Phase 18 `nba_player_gamelogs` table.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | already installed | Async PostgreSQL pool queries | All agent closures use `async with pool.acquire() as conn: await conn.fetch(...)` |
| Pydantic v2 | already installed | `NBAContextSignals` validation gate before writing to GraphState | Non-negotiable per CLAUDE.md; strict=True required |
| structlog | already installed | Structured logging inside closure | Matches every existing agent; `log = structlog.get_logger()` at module level |
| pytest + pytest-asyncio | already installed | Unit tests for the new producer node | 206 tests currently collected; asyncio_mode = "auto" in pyproject.toml |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| datetime.date | stdlib | Compare `game_date` values to compute rest days between consecutive games | `nba_player_gamelogs.game_date` is a Python `date` column |
| unittest.mock (stdlib) | stdlib | Patch `pool.acquire()` for tests without a real database | MagicMock pattern (not AsyncMock) per Phase 4 locked decision |

**Installation:** None required. All dependencies already installed.

---

## Architecture Patterns

### Existing File Structure (additions only)

```
src/sportsbet/
├── prop/
│   ├── nba_agents.py           # existing — _apply_nba_context_adjustments, make_nba_quant_agent
│   ├── nba_executor.py         # existing — LEAGUE_AVG_PACE, LEAGUE_AVG_DEF_RATING constants
│   ├── nba_query_builder.py    # existing — PACE_ADJUSTED_PROPS frozenset
│   └── nba_context_producer.py # NEW — make_nba_context_signals_producer closure factory
├── graph/
│   ├── graph.py                # MODIFIED — wire nba_context_producer_node before nba_quant_agent
│   ├── state.py                # unchanged — nba_context_signals already declared
│   └── models.py               # unchanged — NBAContextSignals already defined
tests/
└── test_nba_context_producer.py  # NEW — unit tests for producer node
```

### Pattern 1: Closure Factory (matches every other agent node)

**What:** `make_nba_context_signals_producer(pool)` returns an async callable compatible with LangGraph's node interface.

**When to use:** Whenever a new LangGraph node needs database access. Injecting pool at construction time (not invocation time) is the locked project pattern from Phase 3.

**Example:**
```python
# Source: src/sportsbet/prop/nba_agents.py make_nba_quant_agent (verified pattern)
def make_nba_context_signals_producer(
    pool: asyncpg.Pool,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    async def nba_context_signals_producer(state: GraphState) -> dict[str, Any]:
        session_id = state.get("session_id", "unknown")
        log.info("nba_context_signals_producer_invoked", session_id=session_id)

        player_id_raw: str = state.get("receiver_gsis_id", "")
        season: int = state.get("season", 2024)
        home_team: str = state.get("home_team", "")
        away_team: str = state.get("away_team", "")

        # ... DB queries ...

        signals = NBAContextSignals(
            opponent_def_rating=...,
            pace_factor=...,
            rest_days=...,
            is_home=...,
        )
        return {"nba_context_signals": signals}

    return nba_context_signals_producer
```

### Pattern 2: Back-to-Back Detection via nba_player_gamelogs

**What:** Query the two most recent games for the player's team, ordered by `game_date DESC`. If the most recent game date is exactly (target_date - 1 day), rest_days = 0. Otherwise rest_days = difference in days.

**Critical constraint:** `nba_player_gamelogs` stores `player_id` (INTEGER) and `team_abbreviation`, `game_date` (DATE). The query must use `team_abbreviation` to match all players on the team, ORDER BY `game_date DESC LIMIT 2`.

**Query pattern (asyncpg):**
```python
# Fetch the last 2 game dates for the team in this season
# to detect back-to-back scheduling.
# team_abbr is derived from state["home_team"] / state["away_team"] and is_home logic.
SQL_B2B = """
    SELECT DISTINCT game_date
    FROM nba_player_gamelogs
    WHERE team_abbreviation = $1
      AND season = $2
    ORDER BY game_date DESC
    LIMIT 2
"""
rows = await conn.fetch(SQL_B2B, team_abbr, season)
```

**rest_days derivation:**
- If 0 rows returned: rest_days = 1 (conservative default — no back-to-back penalty)
- If 1 row (first game of season): rest_days = 1
- If 2 rows: rest_days = max(0, (rows[0]["game_date"] - rows[1]["game_date"]).days - 1)
  - Note: if rows[0] is today's game being queried, use rows[1] and rows[0] spacing. The next game date is not in the DB yet. The spacing between the last TWO completed games is the relevant rest indicator.

**Important nuance:** The `game_date` in `nba_player_gamelogs` reflects completed games. For the upcoming game, the proxy is: "how many days since the most recent completed game?" This requires knowing today's date or the upcoming game date. The `game_id` in GraphState encodes the game; however game date is not stored in `nba_player_gamelogs` for the upcoming game. The practical approach: assume the upcoming game is "today" (or use a configurable target_date defaulting to `date.today()`), then compute `rest_days = (date.today() - latest_game_date).days`. This matches the semantic of "how many days rest before today's game."

### Pattern 3: Opponent Defensive Rating Proxy via nba_player_stats

**What:** The `nba_player_stats` table stores season totals. There is no dedicated `team_defensive_rating` table. A reasonable proxy is the opponent team's players' scoring averages (high average opposing pts per game correlates with weak defense). However, the cleaner approach uses a simpler heuristic: derive an `opponent_def_rating` proxy by querying average `points` per `games_played` (points-allowed proxy) from players on the opposing team roster in `nba_player_stats`.

**Proxy formula:**
```
opponent_avg_pts_per_game = SUM(points) / SUM(games_played) for all players on opponent team in that season
normalized_def_rating = LEAGUE_AVG_DEF_RATING * (opponent_avg_pts_per_game / LEAGUE_AVG_PTS_PER_PLAYER_GAME)
```

Where `LEAGUE_AVG_PTS_PER_PLAYER_GAME` is a constant (~8.0 for per-player averages across roster). This produces a Decimal in the ballpark of `LEAGUE_AVG_DEF_RATING` (115.0).

**Simpler defensible fallback:** If opponent team data is unavailable (new season, empty DB), return `LEAGUE_AVG_DEF_RATING` (115.0 — neutral adjustment, def_ratio = 1.0). This produces no distortion.

**Query pattern:**
```python
SQL_OPP_DEF = """
    SELECT
        CASE WHEN SUM(games_played) > 0
             THEN CAST(SUM(points) AS FLOAT) / SUM(games_played)
             ELSE 0.0
        END AS avg_pts_per_game
    FROM nba_player_stats
    WHERE team_abbreviation = $1
      AND season = $2
      AND games_played > 0
"""
row = await conn.fetchrow(SQL_OPP_DEF, opponent_abbr, season)
```

### Pattern 4: is_home Derivation from GraphState

**What:** `GraphState` already carries `home_team` and `away_team` string fields. The player's team abbreviation is available from `nba_player_gamelogs.team_abbreviation` (queried above). `is_home = (player_team_abbr == home_team)`.

**Approach:** From the back-to-back query (Pattern 2), we already know `team_abbreviation`. Compare with `state["home_team"]`. This eliminates any additional DB query for home/away determination.

### Pattern 5: Graph Wiring — Insert Producer Before nba_quant_agent

**What:** The current graph topology routes `nba_prop_analysis` directly to `nba_quant_agent`. Phase 20 inserts `nba_context_producer` between the router dispatch and `nba_quant_agent`.

**New topology:**
```
router -> nba_context_producer -> nba_quant_agent -> prop_arbitrage_agent
```

**In graph.py create_graph():**
```python
# New optional parameter:
# nba_context_producer_node: Optional node from make_nba_context_signals_producer(pool)

def _nba_context_stub(state: GraphState) -> dict:
    """Stub: returns nba_context_signals=None when no real producer provided."""
    return {"nba_context_signals": None}

active_nba_context_producer = (
    nba_context_producer_node if nba_context_producer_node is not None
    else _nba_context_stub
)

builder.add_node("nba_context_producer", active_nba_context_producer)

# Router dispatches to nba_context_producer (not directly to nba_quant_agent)
# Routing table entry: "nba_quant_agent" -> "nba_context_producer"
# Edge: nba_context_producer -> nba_quant_agent
builder.add_edge("nba_context_producer", "nba_quant_agent")
```

**CRITICAL:** The router currently returns `"nba_quant_agent"` for `request_type == "nba_prop_analysis"`. With Phase 20, the router still returns `"nba_quant_agent"` as the routing key — but the conditional edges mapping maps `"nba_quant_agent"` to the `"nba_context_producer"` node name. This way `route_from_master` needs no changes; only the `add_conditional_edges` mapping in `graph.py` changes `"nba_quant_agent": "nba_context_producer"`.

### Anti-Patterns to Avoid

- **Do not store `opponent_def_rating` as a computed column in DB.** It is a derived signal needed only at inference time. No schema migration needed.
- **Do not use date.today() inside the closure body directly.** Use a default parameter `target_date: date = None` in the factory so tests can inject a fixed date without patching builtins. If `None`, fall back to `date.today()` inside the async node.
- **Do not change the `nba_quant_agent` node name in the routing table.** Keep `route_from_master` returning `"nba_quant_agent"` — only change which physical node the key maps to in `add_conditional_edges`.
- **Do not import NBAContextSignals with TYPE_CHECKING guard.** LangGraph calls `get_type_hints(GraphState)` at runtime. Follow the existing pattern: `from sportsbet.graph.models import NBAContextSignals` at module level (not TYPE_CHECKING). This is a locked Phase 12 decision.
- **Do not use AsyncMock for pool.acquire().** Use MagicMock per Phase 4 locked decision. `AsyncMock` makes `acquire()` return a coroutine, breaking `async with pool.acquire() as conn`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Back-to-back detection | Custom schedule API client | Query `nba_player_gamelogs.game_date` ORDER BY DESC LIMIT 2 | Data already in DB from Phase 18 ingest; no external API needed |
| Pace factor | Parse ESPN or basketball-reference | `LEAGUE_AVG_PACE` (already defined in nba_executor.py) as default, with team-level gamelog density as proxy | Pace variation is ±5% of league average for most teams; the constant is already wired into the adjustment formula |
| Opponent def rating | Integrate an NBA stats API (NBA.com Defensive Rating) | Derive from `nba_player_stats` opponent team scoring totals as proxy | No new API key, no new dependency; calibrated to produce ratios near 1.0 for typical matchups |
| Testing date arithmetic | Complex date fixture system | Pass `target_date` parameter into `make_nba_context_signals_producer(pool, target_date=None)` | Single optional param makes producer fully testable without patching `datetime.date.today` |

---

## Common Pitfalls

### Pitfall 1: Player ID vs Team Abbreviation Lookup

**What goes wrong:** The producer receives `receiver_gsis_id` from GraphState (a string player ID). The B2B query needs `team_abbreviation`. Querying `nba_player_gamelogs` by `player_id` gives the team, but `player_id` in `nba_player_gamelogs` is INTEGER (not VARCHAR). The cast `int(player_id_raw)` must be applied before the query.

**Why it happens:** `PropParams.player_id` is `str` for cross-sport compatibility. `nba_player_gamelogs.player_id` is `Integer` in the ORM. `asyncpg` will raise a type mismatch if the string is passed directly.

**How to avoid:** Apply `int(player_id_raw)` before the asyncpg query parameter, mirroring the locked Phase 12 decision: "player_id cast to int() in NBAQueryBuilder.build()".

**Warning signs:** `asyncpg.exceptions.DataError: invalid input for query argument $1: expected int32, got str`.

### Pitfall 2: Empty nba_player_gamelogs (Cold DB)

**What goes wrong:** If `nba_player_gamelogs` has no rows for the player/team/season (DB not seeded, new season, or player on new team), the B2B query returns 0 rows. The producer must return a valid `NBAContextSignals` with reasonable defaults rather than failing.

**Why it happens:** `nba_player_gamelogs` is populated by `ingest_nba_gamelogs_season()` which is a CLI operation. In development or test environments, the table may be empty.

**How to avoid:** When 0 rows returned for team: `rest_days = 1` (no B2B penalty), `pace_factor = LEAGUE_AVG_PACE` (neutral), `opponent_def_rating = LEAGUE_AVG_DEF_RATING` (neutral), `is_home = (home_team == player_team_abbr)` from state. Return a fully populated `NBAContextSignals` with league-average values rather than `None`.

**Warning signs:** `NBAContextSignals(opponent_def_rating=Decimal("0"), ...)` — zero division in `LEAGUE_AVG_DEF_RATING / context.opponent_def_rating` raises `InvalidOperation`. Guard against zero with fallback to `LEAGUE_AVG_DEF_RATING`.

### Pitfall 3: Routing Table Collision After Graph Rewiring

**What goes wrong:** `route_from_master` returns `"nba_quant_agent"` for `nba_prop_analysis`. After Phase 20, `add_conditional_edges` maps `"nba_quant_agent"` to node `"nba_context_producer"`. If the graph also registers `"nba_quant_agent"` as an independent node reachable by that key, LangGraph will raise a topology error.

**Why it happens:** LangGraph requires each routing key in `add_conditional_edges` to map to exactly one registered node. The mapping `"nba_quant_agent": "nba_context_producer"` uses the routing key `"nba_quant_agent"` to point to the `"nba_context_producer"` node. The `nba_quant_agent` node is then only reachable via the fixed edge from `nba_context_producer`.

**How to avoid:** In `add_conditional_edges`, update the mapping from `"nba_quant_agent": "nba_quant_agent"` to `"nba_quant_agent": "nba_context_producer"`. Keep `builder.add_edge("nba_context_producer", "nba_quant_agent")` for the sequential chain.

**Warning signs:** LangGraph compilation error: `ValueError: Node 'nba_quant_agent' already has an incoming edge`.

### Pitfall 4: Decimal Wrapping for NBAContextSignals

**What goes wrong:** `NBAContextSignals.model_config = ConfigDict(strict=True)`. All `Decimal` fields (`opponent_def_rating`, `pace_factor`) reject raw Python `float` values. `asyncpg` returns `float` from `avg_pts_per_game` column computations.

**Why it happens:** `CAST(SUM(points) AS FLOAT) / SUM(games_played)` returns a Python `float` from asyncpg. Pydantic strict=True raises `ValidationError` if float is assigned to a `Decimal` field.

**How to avoid:** Always wrap: `Decimal(str(round(float_value, 4)))`. This is the locked pattern from Phase 3: "Decimal(str(round(x,6))) wrapping for Wilson CI bounds".

**Warning signs:** `pydantic_core._pydantic_core.ValidationError: ... Input should be a valid Decimal [type=decimal_type]`.

### Pitfall 5: pace_factor Derivation Source

**What goes wrong:** There is no `pace` column in either `nba_player_stats` or `nba_player_gamelogs`. If the producer attempts to derive team pace from raw gamelog data, the result is meaningless (possessions-per-48 requires complete play-by-play tracking).

**Why it happens:** Pace (possessions per 48 minutes) requires counting plays-per-possession, which is not tracked in the existing schema. The `nba_player_stats` table stores only counting stats (points, rebounds, assists, etc.).

**How to avoid:** Use `LEAGUE_AVG_PACE` (100.0) as the default `pace_factor` for all producers in v1. The pace adjustment in `_apply_nba_context_adjustments` produces a ratio of `pace_factor / LEAGUE_AVG_PACE = 1.0` when both equal 100.0, resulting in a neutral (no-op) pace adjustment. This is mathematically correct behavior: if we don't have pace data, we produce no pace distortion. Document this as a known v1 limitation (tracked as tech debt, pace data requires NBA.com team stats endpoint).

---

## Code Examples

Verified patterns from existing codebase:

### NBAContextSignals model (already defined — no changes)
```python
# Source: src/sportsbet/graph/models.py lines 223-253
class NBAContextSignals(BaseModel):
    model_config = ConfigDict(strict=True)
    opponent_def_rating: Decimal  # e.g. Decimal("115.0")
    pace_factor: Decimal           # e.g. Decimal("100.0")
    rest_days: int                 # 0 = back-to-back; 1+ = normal rest
    is_home: bool
```

### Closure factory skeleton (matches make_nba_quant_agent)
```python
# Source pattern: src/sportsbet/prop/nba_agents.py lines 134-160
def make_nba_context_signals_producer(
    pool: asyncpg.Pool,
    target_date: Optional[date] = None,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:

    async def nba_context_signals_producer(state: GraphState) -> dict[str, Any]:
        from datetime import date as date_cls
        today = target_date or date_cls.today()

        player_id_raw: str = state.get("receiver_gsis_id", "")
        season: int = state.get("season", 2024)
        home_team: str = state.get("home_team", "")
        away_team: str = state.get("away_team", "")

        if not player_id_raw:
            # No player context — return league averages (neutral adjustments)
            return {"nba_context_signals": NBAContextSignals(
                opponent_def_rating=LEAGUE_AVG_DEF_RATING,
                pace_factor=LEAGUE_AVG_PACE,
                rest_days=1,
                is_home=False,
            )}

        try:
            player_id = int(player_id_raw)
        except (ValueError, TypeError):
            log.warning("nba_context_producer_invalid_player_id", player_id=player_id_raw)
            return {"nba_context_signals": None}

        async with pool.acquire() as conn:
            # 1. Determine player's team and recent game dates for B2B detection
            team_row = await conn.fetchrow(
                """
                SELECT team_abbreviation, game_date
                FROM nba_player_gamelogs
                WHERE player_id = $1 AND season = $2
                ORDER BY game_date DESC
                LIMIT 1
                """,
                player_id, season,
            )

            if team_row is None:
                # No gamelog data — return league averages
                return {"nba_context_signals": NBAContextSignals(
                    opponent_def_rating=LEAGUE_AVG_DEF_RATING,
                    pace_factor=LEAGUE_AVG_PACE,
                    rest_days=1,
                    is_home=(home_team == ""),
                )}

            team_abbr: str = team_row["team_abbreviation"]
            last_game_date = team_row["game_date"]

            # rest_days = days since last game
            rest_days: int = (today - last_game_date).days
            rest_days = max(0, rest_days)

            # is_home derived from GraphState home_team/away_team
            is_home: bool = (team_abbr == home_team)
            opponent_abbr: str = away_team if is_home else home_team

            # 2. Derive opponent_def_rating proxy from nba_player_stats scoring
            opp_row = await conn.fetchrow(
                """
                SELECT
                    CASE WHEN SUM(games_played) > 0
                         THEN CAST(SUM(points) AS FLOAT) / NULLIF(SUM(games_played), 0)
                         ELSE NULL
                    END AS avg_pts_per_game
                FROM nba_player_stats
                WHERE team_abbreviation = $1 AND season = $2
                """,
                opponent_abbr, season,
            )

            # Compute normalized def_rating proxy
            avg_pts = (
                float(opp_row["avg_pts_per_game"])
                if opp_row and opp_row["avg_pts_per_game"] is not None
                else float(LEAGUE_AVG_DEF_RATING)
            )
            # Normalize: higher opponent scoring avg = higher def_rating (worse defense)
            # League-average player scores ~8 pts/game; scale to 115.0 league def rating
            LEAGUE_AVG_PTS_PER_PLAYER: float = 8.0
            normalized = LEAGUE_AVG_DEF_RATING * Decimal(str(round(
                avg_pts / LEAGUE_AVG_PTS_PER_PLAYER, 6
            )))
            # Clamp to reasonable range [90, 140]
            normalized = max(Decimal("90"), min(Decimal("140"), normalized))

        signals = NBAContextSignals(
            opponent_def_rating=normalized,
            pace_factor=LEAGUE_AVG_PACE,  # v1: neutral pace (no possession data in schema)
            rest_days=rest_days,
            is_home=is_home,
        )
        log.info(
            "nba_context_signals_producer_complete",
            opponent_def_rating=str(normalized),
            rest_days=rest_days,
            is_home=is_home,
        )
        return {"nba_context_signals": signals}

    return nba_context_signals_producer
```

### Graph wiring change in create_graph() (only routing map and edge change)
```python
# Source: src/sportsbet/graph/graph.py (modified section)

# ADD new optional parameter: nba_context_producer_node: Any = None

def _nba_context_stub(state: GraphState) -> dict:
    return {"nba_context_signals": None}

active_nba_context_producer = (
    nba_context_producer_node if nba_context_producer_node is not None
    else _nba_context_stub
)

builder.add_node("nba_context_producer", active_nba_context_producer)

# In add_conditional_edges mapping:
# BEFORE: "nba_quant_agent": "nba_quant_agent"
# AFTER:  "nba_quant_agent": "nba_context_producer"

# ADD fixed edge:
builder.add_edge("nba_context_producer", "nba_quant_agent")
```

### create_graph_with_sqlite() addition
```python
# Source: src/sportsbet/graph/graph.py (create_graph_with_sqlite)
nba_context_producer_node = None
if pool is not None:
    from sportsbet.prop.nba_context_producer import make_nba_context_signals_producer
    nba_context_producer_node = make_nba_context_signals_producer(pool)
```

### Back-to-back detection test pattern (asyncpg MagicMock)
```python
# Source pattern: tests/test_context.py (MagicMock for pool.acquire)
from unittest.mock import MagicMock, AsyncMock, patch

def make_mock_pool(rows_by_query: list) -> MagicMock:
    """Return a MagicMock pool whose acquire().fetchrow/.fetch returns rows in order."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=rows_by_query)
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| NBAContextSignals caller-supplied (manual injection only) | NBAContextSignals auto-populated by `NBAContextSignalsProducer` node before `nba_quant_agent` | Phase 20 (this phase) | Four-stage contextual adjustment fires automatically in all automated `nba_prop_analysis` pipeline runs |
| pace_factor derived externally | LEAGUE_AVG_PACE constant (neutral, no distortion) | Phase 20 v1 design | Pace adjustment produces ratio = 1.0 for all teams; no error but no pace signal. V2 can add NBA.com team pace endpoint. |

---

## Open Questions

1. **Should `pace_factor` be team-specific or always `LEAGUE_AVG_PACE`?**
   - What we know: `nba_player_stats` and `nba_player_gamelogs` contain no possession or pace columns. Pace (possessions per 48 minutes) requires tracking all play stoppages from play-by-play data, which is not ingested.
   - What's unclear: Whether to add a separate team-level pace lookup to nba_api (`TeamDashboardByGeneralSplits` with PacePerPoss) or defer to v2.
   - Recommendation: Use `LEAGUE_AVG_PACE` for v1. The `pace_factor / LEAGUE_AVG_PACE = 1.0` ratio is a neutral no-op in `_apply_nba_context_adjustments`. Document as tech debt. Adding pace in v2 requires only changing the producer — the consumer (`_apply_nba_context_adjustments`) is already correct.

2. **How accurate is the `opponent_def_rating` proxy from `nba_player_stats` scoring totals?**
   - What we know: The real NBA defensive rating (points allowed per 100 possessions) requires possession counting. The `nba_player_stats` proxy (opponent team scoring average per player) is a rough correlation — elite offenses score more, which loosely corresponds to poor defense. The proxy produces a Decimal near `LEAGUE_AVG_DEF_RATING` for typical teams.
   - What's unclear: The proxy direction — a high opponent scoring average might mean strong offense (not weak defense). The NBA does not separate offensive contribution from defensive deficiency in this table.
   - Recommendation: Accept the proxy for v1 with documented limitations. The formula is clamped to [90, 140] so extreme values cannot distort Kelly sizing. In v2, the proper source is NBA.com's `TeamDashboardByOpponent` endpoint.

3. **What player_id to use when `receiver_gsis_id` is empty string?**
   - What we know: `receiver_gsis_id` is initialized as empty string `""` in GraphState for non-kinematic routes (Phase 7 locked decision). NBA prop routes set it to the numeric NBA player ID (as string).
   - What's unclear: Whether the producer should return `None` or league-average defaults when `receiver_gsis_id == ""`.
   - Recommendation: Return `NBAContextSignals` with `LEAGUE_AVG_DEF_RATING`, `LEAGUE_AVG_PACE`, `rest_days=1`, `is_home=False` when player_id is empty. This is safer than returning `None` — it preserves the four-stage pipeline activation while producing neutral adjustments that do not distort the base probability.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio (asyncio_mode = "auto") |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_nba_context_producer.py -x -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-05 | Producer writes NBAContextSignals to state for back-to-back player (rest_days=0) | unit | `python -m pytest tests/test_nba_context_producer.py::test_producer_detects_back_to_back -x` | Wave 0 |
| PROP-05 | Producer writes NBAContextSignals with is_home=True when player_team == home_team | unit | `python -m pytest tests/test_nba_context_producer.py::test_producer_is_home_derivation -x` | Wave 0 |
| NBA-02 | Producer calculates opponent_def_rating proxy from nba_player_stats | unit | `python -m pytest tests/test_nba_context_producer.py::test_producer_opponent_def_rating_proxy -x` | Wave 0 |
| NBA-02 | Producer returns league-average defaults when no gamelog rows available | unit | `python -m pytest tests/test_nba_context_producer.py::test_producer_empty_db_defaults -x` | Wave 0 |
| PROP-05 + NBA-02 | Integration: nba_context_signals is non-None after nba_prop_analysis pipeline run | integration | `python -m pytest tests/test_nba_context_producer.py::test_integration_context_signals_populated -x` | Wave 0 |
| PROP-05 + NBA-02 | _apply_nba_context_adjustments produces different probability vs unadjusted baseline | unit | `python -m pytest tests/test_nba_context_producer.py::test_adjusted_prob_differs_from_baseline -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_nba_context_producer.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green (currently 206 collected) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_nba_context_producer.py` — covers all 6 test cases above (new file, does not exist yet)
- [ ] `src/sportsbet/prop/nba_context_producer.py` — producer module (new file, does not exist yet)

---

## Sources

### Primary (HIGH confidence)

- `src/sportsbet/prop/nba_agents.py` lines 1-222 — `_apply_nba_context_adjustments` four-stage pipeline verified; `make_nba_quant_agent` closure factory verified; `state.get("nba_context_signals")` always returns None in automated runs confirmed
- `src/sportsbet/graph/models.py` lines 223-253 — `NBAContextSignals` Pydantic model fields verified (`opponent_def_rating`, `pace_factor`, `rest_days`, `is_home`; all strict=True)
- `src/sportsbet/graph/state.py` lines 86-90, 140 — `nba_context_signals: Optional[NBAContextSignals]` field confirmed; docstring confirms "None when request is NFL (non-NBA) or NBA context not provided"
- `src/sportsbet/graph/graph.py` lines 246-248, 263-266 — `nba_quant_agent` node registration and routing table entry confirmed; conditional edge mapping `"nba_quant_agent": "nba_quant_agent"` is the specific line to change
- `src/sportsbet/db/models.py` lines 320-361 — `NBAPlayerGameLog` schema confirmed: `player_id` Integer, `team_abbreviation` String(3), `game_date` Date, `is_home` Boolean, `season` SmallInteger; composite indexes `idx_nba_gamelog_player_season`, `idx_nba_gamelog_game_date` present
- `src/sportsbet/db/models.py` lines 282-317 — `NBAPlayerStats` schema: `player_id` Integer, `team_abbreviation` String(5), `points` Integer, `games_played` SmallInteger; index `idx_nba_team_season` present
- `src/sportsbet/prop/nba_executor.py` lines 61-67 — `LEAGUE_AVG_PACE = Decimal("100.0")`, `LEAGUE_AVG_DEF_RATING = Decimal("115.0")` confirmed; these are the constants already used in `_apply_nba_context_adjustments`
- `.planning/v1.0-MILESTONE-AUDIT.md` lines 34-38 — INT-3 description: "NBAContextSignals has no pipeline producer — NBA contextual adjustments silently skipped in automated runs"
- `.planning/STATE.md` — Phase 12 locked decisions confirming `NBAContextSignals` runtime import pattern; player_id cast to int() in NBAQueryBuilder.build()

### Secondary (MEDIUM confidence)

- `src/sportsbet/ingestion/nba_gamelogs.py` — confirms `nba_player_gamelogs` populated from `PlayerGameLogs` endpoint; `game_date` as Python `date` object confirmed; `is_home` and `opponent_team` derived at ingest time
- `src/sportsbet/prop/nba_query_builder.py` lines 1-36 — confirms `int(params.player_id)` pattern for asyncpg INTEGER column compatibility

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries installed; no new dependencies needed; pattern exactly matches existing agent nodes
- Architecture: HIGH — exact file locations, column names, routing table entries, and constant values verified from direct source read
- Pitfalls: HIGH — derived from locked decisions in STATE.md, existing asyncpg integer cast pattern, and NBAContextSignals strict=True model

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (stable internal domain; no external API dependencies in core implementation)
