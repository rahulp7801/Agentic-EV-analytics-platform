"""NBAQueryBuilder: parameterized SQL dispatch for nba_player_stats season-aggregate data.

Data model note:
    nba_player_stats stores season TOTALS (one row per player per season from
    LeagueDashPlayerStats Totals mode). There are NO per-game rows. Probability
    must be derived via normal approximation using per-game averages computed
    from season totals divided by games_played.

    For CONDITIONAL queries (opponent_team, home_away, last_n_games, teammate_out set),
    NBAQueryBuilder dispatches to nba_player_gamelogs templates instead. Gamelogs
    provide per-game binary outcome counts, enabling Wilson CI (frequency counting)
    rather than NormalDist approximation.

Security invariant (identical to prop/query_builder.py):
    User-supplied data (player_id, season) NEVER appears in the SQL string.
    All values are passed as positional asyncpg $N params.
    Column names in SELECT come exclusively from NBA_PROP_COLUMN_MAP or
    NBA_GAMELOG_COLUMN_MAP (static dicts) keyed by prop_type Literal — prop_type
    is validated by Pydantic before build() is ever called.
    No f-string SQL for user data. No string interpolation of user values. Period.

player_id cast:
    nba_player_stats.player_id and nba_player_gamelogs.player_id are INTEGER
    (not VARCHAR). PropParams.player_id is str for cross-sport compat.
    NBAQueryBuilder.build() always casts int(params.player_id) for $1.

Dispatch logic (Phase 18 updated):
    Conditional = any of (last_n_games, teammate_out, opponent_team, home_away) set:
        - prop_type == "double_double" → season-aggregate path (gamelog DD not modeled)
        - prop_type == "pra"          → _NBA_GAMELOG_PRA_TEMPLATE + situational filters
        - else                         → _NBA_GAMELOG_SINGLE_TEMPLATE + situational filters
    Unconditional (all situational fields None):
        - prop_type == "pra"          → _NBA_PRA_TEMPLATE
        - prop_type == "double_double" → _NBA_DD_TEMPLATE
        - else                         → _NBA_SINGLE_STAT_TEMPLATE
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
# Phase 18: nba_player_gamelogs column map (per-game binary frequency path)
# Used for conditional queries (opponent_team, home_away, last_n_games set).
# nba_player_gamelogs columns may differ from nba_player_stats column names.
# ---------------------------------------------------------------------------

NBA_GAMELOG_COLUMN_MAP: dict[str, str] = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes": "threes_made",
    "steals": "steals",
    "blocks": "blocks",
    "pra": None,  # composite — handled by _NBA_GAMELOG_PRA_TEMPLATE
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


# ---------------------------------------------------------------------------
# Phase 18: nba_player_gamelogs SQL templates (conditional path)
# $1 = player_id (int)
# $2 = season    (int)
# $3 = line      (float)
# Situational $N params appended dynamically in NBAQueryBuilder.build()
# {col} substituted from NBA_GAMELOG_COLUMN_MAP — allowlist only, never user input
# ---------------------------------------------------------------------------

# Single-stat gamelog template: per-game binary frequency (COUNT/SUM CASE)
_NBA_GAMELOG_SINGLE_TEMPLATE = """\
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN {col} > $3 THEN 1 ELSE 0 END) AS successes,
    SUM(CASE WHEN {col} = $3 THEN 1 ELSE 0 END) AS pushes,
    AVG({col}::float) AS mean_val
FROM nba_player_gamelogs
WHERE player_id = $1
  AND season >= $2
  AND {col} IS NOT NULL
"""

# PRA composite gamelog template: points + rebounds + assists binary frequency
_NBA_GAMELOG_PRA_TEMPLATE = """\
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN (points + rebounds + assists) > $3 THEN 1 ELSE 0 END) AS successes,
    SUM(CASE WHEN (points + rebounds + assists) = $3 THEN 1 ELSE 0 END) AS pushes,
    AVG((points + rebounds + assists)::float) AS mean_val
FROM nba_player_gamelogs
WHERE player_id = $1
  AND season >= $2
  AND points IS NOT NULL AND rebounds IS NOT NULL AND assists IS NOT NULL
"""


def _is_conditional(params: "PropParams") -> bool:
    """Return True if any Phase 18 situational filter field is set."""
    return bool(
        params.as_of_date is not None
        or params.last_n_games is not None
        or params.teammate_out
        or params.teammate_out_contexts
        or params.opponent_team is not None
        or params.home_away is not None
    )


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
            for user values and {col} substituted from the static NBA_PROP_COLUMN_MAP
            or NBA_GAMELOG_COLUMN_MAP.
            Pass to asyncpg as: await conn.fetchrow(sql, *args).

        Notes
        -----
        args[0] = int(params.player_id): nba_player_stats.player_id and
        nba_player_gamelogs.player_id are INTEGER. PropParams.player_id is str for
        cross-sport compat — cast required here.
        asyncpg raises DataError on str vs INTEGER mismatch without explicit cast.

        Phase 18 conditional dispatch:
        When any situational filter is set (opponent_team, home_away, last_n_games,
        teammate_out), dispatch to nba_player_gamelogs templates for per-game binary
        frequency counting. double_double is excluded from gamelog path (no per-game
        composite binary model in v1 — falls through to season-aggregate path).

        Gamelog home_away: nba_player_gamelogs uses is_home BOOLEAN column (True/False),
        not the "home"/"away" string used by player_stats. Conversion happens here:
        "home" -> True, "away" -> False in the args tuple.
        """
        player_id_int: int = int(params.player_id)

        # --- Phase 18: conditional gamelog path ---
        # Dispatch to nba_player_gamelogs when any situational filter is set.
        # double_double excluded: no per-game composite binary model in v1.
        if _is_conditional(params) and (params.prop_type != "double_double" or params.as_of_date is not None):
            args: list[object] = [player_id_int, params.season, float(params.line)]
            next_idx = 4

            # Select gamelog template from static allowlist (not user input)
            if params.prop_type == "double_double":
                # Actual per-game double-doubles, including steals and blocks.
                categories = " + ".join(
                    f"CASE WHEN {column} >= 10 THEN 1 ELSE 0 END"
                    for column in ("points", "rebounds", "assists", "steals", "blocks")
                )
                sql = (
                    "SELECT COUNT(*) AS total, "
                    f"SUM(CASE WHEN ({categories}) >= 2 THEN 1 ELSE 0 END) AS successes, "
                    "NULL AS mean_val FROM nba_player_gamelogs "
                    "WHERE player_id = $1 AND season >= $2\n"
                )
                args = [player_id_int, params.season]
                next_idx = 3
            elif params.prop_type == "pra":
                sql: str = _NBA_GAMELOG_PRA_TEMPLATE
            else:
                col: str = NBA_GAMELOG_COLUMN_MAP[params.prop_type]  # type: ignore[index]
                sql = _NBA_GAMELOG_SINGLE_TEMPLATE.format(col=col)

            # Append situational filters — same security invariants as PropQueryBuilder:
            # column names from static allowlist; values in positional $N args only.

            cutoff_idx = None
            if params.as_of_date is not None:
                cutoff_idx = next_idx
                sql += f"  AND game_date < ${next_idx}\n"
                args.append(params.as_of_date)
                next_idx += 1

            # opponent_team filter
            if params.opponent_team is not None:
                sql = sql + f"  AND opponent_team = ${next_idx}\n"
                args.append(params.opponent_team)
                next_idx += 1

            # home_away filter — nba_player_gamelogs uses is_home BOOLEAN (not string)
            if params.home_away is not None:
                sql = sql + f"  AND is_home = ${next_idx}\n"
                args.append(params.home_away == "home")  # "home" -> True, "away" -> False
                next_idx += 1

            # teammate_out filter — uses nba_player_gamelogs absence by player_name.
            # nba_player_gamelogs has player_name column; NOT EXISTS checks teammate
            # was absent on the same game_date (didn't appear in gamelogs = didn't play).
            if params.teammate_out:
                for teammate_name in params.teammate_out:
                    sql = sql + (
                        f"  AND NOT EXISTS (\n"
                        f"      SELECT 1 FROM nba_player_gamelogs gl2\n"
                        f"      WHERE gl2.game_date = nba_player_gamelogs.game_date\n"
                        f"        AND gl2.player_name ILIKE ${next_idx}\n"
                        f"  )\n"
                    )
                    args.append(teammate_name)
                    next_idx += 1

            # last_n_games filter — game_id IN subquery (gamelogs have game_id)
            if params.last_n_games is not None:
                subq_conditions = "player_id = $1 AND season >= $2"
                if cutoff_idx is not None:
                    subq_conditions += f" AND game_date < ${cutoff_idx}"
                if params.opponent_team is not None:
                    opp_arg_idx = args.index(params.opponent_team) + 1
                    subq_conditions += f" AND opponent_team = ${opp_arg_idx}"
                sql = sql + (
                    f"  AND game_id IN (\n"
                    f"      SELECT game_id FROM nba_player_gamelogs\n"
                    f"      WHERE {subq_conditions}\n"
                    f"      ORDER BY game_date DESC\n"
                    f"      LIMIT ${next_idx}\n"
                    f"  )\n"
                )
                args.append(params.last_n_games)
                next_idx += 1

            return sql, tuple(args)

        # --- Season-aggregate path (unconditional, or double_double) ---
        base_args: tuple[object, ...] = (player_id_int, params.season)

        if params.prop_type == "pra":
            return _NBA_PRA_TEMPLATE, base_args

        if params.prop_type == "double_double":
            return _NBA_DD_TEMPLATE, base_args

        # Single-stat path: look up column from allowlist, never from user input
        agg_col: str = NBA_PROP_COLUMN_MAP[params.prop_type]
        agg_sql: str = _NBA_SINGLE_STAT_TEMPLATE.format(col=agg_col)
        return agg_sql, base_args
