"""PropQueryBuilder: static SQL template dispatch with FilterKey guard for player props.

Security invariant: user-supplied data (player_id, season, line, filter values) NEVER
appears in the SQL string. All values are passed as positional asyncpg $N params.
Column names in filter clauses come exclusively from PROP_ALLOWED_FILTER_KEYS or
NFL_SITUATIONAL_ALLOWED_KEYS (static frozensets), not from user input — this is the
structural injection prevention layer.
Column names in SELECT come exclusively from PROP_COLUMN_MAP (a static dict) keyed by
prop_type Literal — prop_type is validated by Pydantic before build() is ever called.

No f-string SQL for user data. No string interpolation of user values. Period.

Phase 18 situational filter extensions (SC-4):
    Situational filters are appended AFTER the base params.filters loop. Order matters:
    1. opponent_team  (AND opponent_team = $N)
    2. home_away      (AND home_away = $N  — "home"/"away" string in player_stats)
    3. teammate_out   (AND EXISTS(...injury_reports with INTERVAL date window...))
       Date-window approximation: injury_reports.game_id is nullable in v1 schema
       (migration 0005). Direct game_id join is unreliable. INTERVAL window of
       [-2 days, +1 day] around the game date is the v1 solution.
    4. last_n_games   (AND (season,week) IN (SELECT ... ORDER BY ... LIMIT $N))
       Applied LAST so the subquery picks the most-recent N games that already pass
       the opponent/location filters above — correct "last N games vs opponent" semantics.
       Uses (season, week) tuple as the stable key because existing player_stats rows
       have NULL game_id (game_id added as nullable in migration 0005).

Security invariants for situational clauses:
    - Column names (opponent_team, home_away, is_home, etc.) come from
      NFL_SITUATIONAL_ALLOWED_KEYS frozenset — NOT from user input.
    - All user-supplied VALUES (team abbreviation, "home"/"away", player IDs,
      last_n_games integer) are ALWAYS placed in the positional args tuple.
    - f-string is used only to inject $N index numbers and static column names
      from the allowlist — never user data.
"""
from __future__ import annotations

import structlog

from sportsbet.graph.models import PropParams

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Allowed filter column names (allowlist — NOT derived from user input)
# ---------------------------------------------------------------------------

PROP_ALLOWED_FILTER_KEYS: frozenset[str] = frozenset({"week", "team"})

# ---------------------------------------------------------------------------
# Phase 18 situational filter column allowlist
# Column names for situational WHERE clauses — static frozenset, NOT user input.
# player_stats uses string "home"/"away" in home_away column (Option A migration 0005).
# ---------------------------------------------------------------------------

NFL_SITUATIONAL_ALLOWED_KEYS: frozenset[str] = frozenset({
    "opponent_team",
    "home_away",
})

# ---------------------------------------------------------------------------
# Column map: prop_type Literal -> player_stats column name
# All 11 NFL prop types + NBA types not queried by PropQueryBuilder (NBA uses
# a separate query path — kept here for completeness and forward-compat).
# Column names are Python string literals — NOT user input.
# ---------------------------------------------------------------------------

PROP_COLUMN_MAP: dict[str, str] = {
    # NFL passing
    "pass_yds": "passing_yards",
    "pass_tds": "passing_tds",
    "completions": "completions",
    "attempts": "attempts",
    # NFL rushing
    "rush_yds": "rushing_yards",
    "rush_tds": "rushing_tds",
    "carries": "carries",
    # NFL receiving
    "rec_yds": "receiving_yards",
    "rec_tds": "receiving_tds",
    "receptions": "receptions",
    "targets": "targets",
    # NBA (forwarded to NBA query path — not handled by _NFL_PROP_TEMPLATE)
    "points": "pts",
    "rebounds": "reb",
    "assists": "ast",
    "threes": "fg3m",
    "steals": "stl",
    "blocks": "blk",
    "pra": "pra",
    "double_double": "double_double",  # NBA composite prop — forwarded to NBAQueryBuilder path
}

# ---------------------------------------------------------------------------
# Static SQL template
# $1 = player_id  (str)
# $2 = season     (int)
# $3 = line       (float — cast to float to avoid asyncpg NUMERIC/SMALLINT ambiguity)
# {col} substituted from PROP_COLUMN_MAP[params.prop_type] — allowlist only, never user input
# ---------------------------------------------------------------------------

_NFL_PROP_TEMPLATE = """\
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN {col} > $3 THEN 1 ELSE 0 END) AS successes,
    SUM(CASE WHEN {col} = $3 THEN 1 ELSE 0 END) AS pushes,
    AVG({col}::float) AS mean_val
FROM player_stats
WHERE player_id = $1
  AND season >= $2
  AND {col} IS NOT NULL
"""


class PropQueryBuilder:
    """Builds parameterized asyncpg SQL queries from validated PropParams.

    The build() classmethod is the sole public API. It:
    1. Selects the player_stats column from PROP_COLUMN_MAP by prop_type (Literal — already validated).
    2. Substitutes the column name into the static _NFL_PROP_TEMPLATE (not user data).
    3. Appends allowed filter clauses using column names from PROP_ALLOWED_FILTER_KEYS only.
    4. Returns (sql_string, args_tuple) where args_tuple contains all $N values.

    User-supplied values (player_id, season, line, filter values) are ALWAYS in args_tuple,
    never interpolated into the SQL string.
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
            for user values and {col} substituted from the static PROP_COLUMN_MAP.
            Pass to asyncpg as: await conn.fetchrow(sql, *args).

        Notes
        -----
        args[2] = float(params.line): asyncpg requires a Python float for comparison
        against integer/smallint stat columns — Decimal triggers NUMERIC vs SMALLINT
        operator ambiguity error in PostgreSQL.

        Phase 18 situational filters are appended after the base filters loop.
        Append order: opponent_team -> home_away -> teammate_out -> last_n_games.
        last_n_games is applied last so its subquery can reuse opponent_team filter
        for correct "last N vs opponent" semantics.
        """
        col: str = PROP_COLUMN_MAP[params.prop_type]  # allowlist substitution, not user input

        # Substitute column name from static map — column name is NOT user data
        sql: str = _NFL_PROP_TEMPLATE.format(col=col)

        # Base positional args: $1=player_id, $2=season, $3=line (float for asyncpg compat)
        args: list[object] = [params.player_id, params.season, float(params.line)]

        # FilterKey guard: only PROP_ALLOWED_FILTER_KEYS pass through
        # Column names come from the allowlist (not user input) — safe for SQL concatenation.
        # Values always go into positional args — never interpolated.
        next_idx = 4
        for key, value in params.filters.items():
            if key not in PROP_ALLOWED_FILTER_KEYS:
                log.warning("prop_unknown_filter_key_dropped", key=key)
                continue
            # key is from PROP_ALLOWED_FILTER_KEYS (static frozenset) — not user data
            sql = sql + f"  AND {key} = ${next_idx}\n"
            args.append(value)
            next_idx += 1

        # --- Phase 18 situational filter clauses ---
        # All column names from NFL_SITUATIONAL_ALLOWED_KEYS (static frozenset) — not user input.
        # All values in positional $N args — never interpolated into SQL string.

        # opponent_team filter — applied before last_n_games for correct subquery semantics
        if params.opponent_team is not None:
            sql = sql + f"  AND opponent_team = ${next_idx}\n"
            args.append(params.opponent_team)
            next_idx += 1

        # home_away filter — player_stats.home_away is "home"/"away" string (Option A schema)
        # "home"/"away" Literal validated by Pydantic before build() is called
        if params.home_away is not None:
            sql = sql + f"  AND home_away = ${next_idx}\n"
            args.append(params.home_away)
            next_idx += 1

        # teammate_out filter — date-window approximation via injury_reports table
        # Uses INTERVAL window of [-2 days, +1 day] around the game date.
        # Direct game_id join is unreliable because injury_reports.game_id is nullable
        # in v1 schema (migration 0005). Date-window is v1 solution (RESEARCH.md Pitfall 4).
        # Teammate player IDs are in args (positional) — never embedded in SQL string.
        if params.teammate_out:
            for teammate_id in params.teammate_out:
                sql = sql + (
                    f"  AND EXISTS (\n"
                    f"      SELECT 1 FROM injury_reports ir\n"
                    f"      WHERE ir.player_name = ${next_idx}\n"
                    f"        AND ir.status = 'Out'\n"
                    f"        AND ir.scraped_at BETWEEN\n"
                    f"            (SELECT MIN(game_date) FROM games g"
                    f" WHERE g.season = player_stats.season"
                    f" AND g.week = player_stats.week) - INTERVAL '2 days'\n"
                    f"            AND\n"
                    f"            (SELECT MIN(game_date) FROM games g"
                    f" WHERE g.season = player_stats.season"
                    f" AND g.week = player_stats.week) + INTERVAL '1 day'\n"
                    f"  )\n"
                )
                args.append(teammate_id)
                next_idx += 1

        # teammate_out_contexts: player_stats absence detection by team+position.
        # When a player (e.g., "QB from KC") has no stat row for a given week,
        # they didn't play — this is a reliable historical proxy for injury absence.
        # Preferred over the injury_reports INTERVAL path because player_stats has
        # multi-season history; injury_reports only has live/recent data.
        # team and position come from StaticDict (NFL_SITUATIONAL_ALLOWED_KEYS expanded) — not user input.
        if params.teammate_out_contexts:
            for ctx in params.teammate_out_contexts:
                team = ctx.get("team", "")
                position = ctx.get("position", "")
                if not team or not position or position == "Unknown":
                    continue
                sql = sql + (
                    f"  AND NOT EXISTS (\n"
                    f"      SELECT 1 FROM player_stats ps2\n"
                    f"      WHERE ps2.season = player_stats.season\n"
                    f"        AND ps2.week = player_stats.week\n"
                    f"        AND ps2.team = ${next_idx}\n"
                    f"        AND ps2.position = ${next_idx + 1}\n"
                    f"        AND (\n"
                    f"          COALESCE(ps2.passing_yards, 0) > 0\n"
                    f"          OR COALESCE(ps2.rushing_yards, 0) > 0\n"
                    f"          OR COALESCE(ps2.receiving_yards, 0) > 0\n"
                    f"        )\n"
                    f"  )\n"
                )
                args.append(team)
                args.append(position)
                next_idx += 2

        # last_n_games filter — (season, week) IN subquery with ORDER BY + LIMIT $N
        # Applied LAST so the subquery's opponent_team filter (if present) narrows
        # the recency window correctly for "last N games vs opponent" queries.
        # Uses (season, week) tuple as the stable composite key — existing player_stats
        # rows have NULL game_id (game_id added as nullable in migration 0005).
        if params.last_n_games is not None:
            subq_conditions = "player_id = $1 AND season >= $2"
            # Reuse opponent_team filter in subquery if present
            # opponent_team is always the first filter appended after base args (index 4)
            # when no params.filters keys are present. Track its position via current args.
            if params.opponent_team is not None:
                # Find the index of opponent_team in args (1-indexed for asyncpg $N)
                opp_arg_idx = args.index(params.opponent_team) + 1
                subq_conditions += f" AND opponent_team = ${opp_arg_idx}"
            sql = sql + (
                f"  AND (season, week) IN (\n"
                f"      SELECT season, week FROM player_stats\n"
                f"      WHERE {subq_conditions}\n"
                f"      ORDER BY season DESC, week DESC\n"
                f"      LIMIT ${next_idx}\n"
                f"  )\n"
            )
            args.append(params.last_n_games)
            next_idx += 1

        return sql, tuple(args)
