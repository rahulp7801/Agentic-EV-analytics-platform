"""NBAQueryBuilder: parameterized SQL dispatch for nba_player_stats season-aggregate data.

Data model note:
    nba_player_stats stores season TOTALS (one row per player per season from
    LeagueDashPlayerStats Totals mode). There are NO per-game rows. Probability
    must be derived via normal approximation using per-game averages computed
    from season totals divided by games_played.

Security invariant (identical to prop/query_builder.py):
    User-supplied data (player_id, season) NEVER appears in the SQL string.
    All values are passed as positional asyncpg $N params.
    Column names in SELECT come exclusively from NBA_PROP_COLUMN_MAP (a static dict)
    keyed by prop_type Literal — prop_type is validated by Pydantic before build()
    is ever called. No f-string SQL for user data. No string interpolation of user
    values. Period.

player_id cast:
    nba_player_stats.player_id is INTEGER (not VARCHAR). PropParams.player_id is str
    for cross-sport compat. NBAQueryBuilder.build() always casts int(params.player_id)
    for $1 — asyncpg would raise DataError on str vs INTEGER mismatch.

Dispatch logic:
    - prop_type == "pra"          → _NBA_PRA_TEMPLATE (points + rebounds + assists composite)
    - prop_type == "double_double" → _NBA_DD_TEMPLATE (per-component averages for inclusion-exclusion)
    - else                         → _NBA_SINGLE_STAT_TEMPLATE (single column aggregate)
"""
from __future__ import annotations

from decimal import Decimal

from sportsbet.graph.models import PropParams

# ---------------------------------------------------------------------------
# Column map: prop_type Literal -> nba_player_stats column name
# Keys are NBA prop_type Literals. Values are static Python string literals —
# NOT user input. This allowlist is the structural injection prevention layer.
# ---------------------------------------------------------------------------

NBA_PROP_COLUMN_MAP: dict[str, str] = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes": "threes_made",
    "steals": "steals",
    "blocks": "blocks",
}

# ---------------------------------------------------------------------------
# Coefficient of Variation (CV) heuristics per RESEARCH.md
# Used by nba_executor.py to estimate per-game std dev from season averages.
# std = avg_per_game * CV_MAP[prop_type]; floored at 0.5 to prevent sigma=0.
# ---------------------------------------------------------------------------

NBA_PROP_CV_MAP: dict[str, Decimal] = {
    "points": Decimal("0.35"),
    "rebounds": Decimal("0.45"),
    "assists": Decimal("0.50"),
    "threes": Decimal("0.55"),
    "steals": Decimal("0.65"),
    "blocks": Decimal("0.65"),
    "pra": Decimal("0.35"),
    "double_double": Decimal("0.40"),
}

# ---------------------------------------------------------------------------
# Props where pace adjustment is meaningful (volume props only)
# Pace adjustment deferred to Plan 02 NBAQuantAgent — this frozenset gates it.
# ---------------------------------------------------------------------------

PACE_ADJUSTED_PROPS: frozenset[str] = frozenset({"points", "rebounds", "assists", "pra"})

# ---------------------------------------------------------------------------
# SQL templates
# $1 = player_id (int — nba_player_stats.player_id is INTEGER)
# $2 = season    (int)
# {col} substituted from NBA_PROP_COLUMN_MAP — allowlist only, never user input
# ---------------------------------------------------------------------------

# Single-stat template: used for points, rebounds, assists, threes, steals, blocks
_NBA_SINGLE_STAT_TEMPLATE = """\
SELECT
    SUM(games_played) AS total_games,
    SUM({col}) AS total_stat,
    AVG({col}::float / NULLIF(games_played, 0)) AS avg_per_game
FROM nba_player_stats
WHERE player_id = $1
  AND season >= $2
  AND games_played IS NOT NULL
  AND {col} IS NOT NULL
"""

# PRA composite template: points + rebounds + assists per game
_NBA_PRA_TEMPLATE = """\
SELECT
    SUM(games_played) AS total_games,
    SUM(points + rebounds + assists) AS total_stat,
    AVG((points + rebounds + assists)::float / NULLIF(games_played, 0)) AS avg_per_game
FROM nba_player_stats
WHERE player_id = $1
  AND season >= $2
  AND games_played IS NOT NULL
  AND points IS NOT NULL
  AND rebounds IS NOT NULL
  AND assists IS NOT NULL
"""

# Double-double template: per-component averages for inclusion-exclusion probability
# Returns avg_pts, avg_reb, avg_ast — used by _double_double_prob() in nba_executor.py
_NBA_DD_TEMPLATE = """\
SELECT
    SUM(games_played) AS total_games,
    AVG(points::float / NULLIF(games_played, 0)) AS avg_pts,
    AVG(rebounds::float / NULLIF(games_played, 0)) AS avg_reb,
    AVG(assists::float / NULLIF(games_played, 0)) AS avg_ast
FROM nba_player_stats
WHERE player_id = $1
  AND season >= $2
  AND games_played IS NOT NULL
"""


class NBAQueryBuilder:
    """Builds parameterized asyncpg SQL queries for NBA player props.

    The build() classmethod is the sole public API. It dispatches to one of three
    SQL templates based on prop_type:
    - "pra"          → _NBA_PRA_TEMPLATE
    - "double_double" → _NBA_DD_TEMPLATE
    - all other NBA  → _NBA_SINGLE_STAT_TEMPLATE

    User-supplied values (player_id, season) are ALWAYS in args tuple, never
    interpolated into the SQL string. player_id is cast to int() because
    nba_player_stats.player_id is INTEGER (not VARCHAR like player_stats).
    """

    @classmethod
    def build(cls, params: PropParams) -> tuple[str, tuple[object, ...]]:
        """Build a parameterized SQL query for the given PropParams.

        Parameters
        ----------
        params:
            A fully validated PropParams instance (Pydantic ensures Literal prop_type,
            season range, etc. are already correct before build() is called).

        Returns
        -------
        tuple[str, tuple[object, ...]]
            (sql_string, args_tuple) where sql_string contains only $N placeholders
            for user values and {col} substituted from the static NBA_PROP_COLUMN_MAP.
            Pass to asyncpg as: await conn.fetchrow(sql, *args).

        Notes
        -----
        args[0] = int(params.player_id): nba_player_stats.player_id is INTEGER.
        PropParams.player_id is str for cross-sport compat — cast required here.
        asyncpg raises DataError on str vs INTEGER mismatch without explicit cast.
        """
        player_id_int: int = int(params.player_id)
        args: tuple[object, ...] = (player_id_int, params.season)

        if params.prop_type == "pra":
            return _NBA_PRA_TEMPLATE, args

        if params.prop_type == "double_double":
            return _NBA_DD_TEMPLATE, args

        # Single-stat path: look up column from allowlist, never from user input
        col: str = NBA_PROP_COLUMN_MAP[params.prop_type]
        sql: str = _NBA_SINGLE_STAT_TEMPLATE.format(col=col)
        return sql, args
