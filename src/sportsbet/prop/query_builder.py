"""PropQueryBuilder: static SQL template dispatch with FilterKey guard for player props.

Security invariant: user-supplied data (player_id, season, line, filter values) NEVER
appears in the SQL string. All values are passed as positional asyncpg $N params.
Column names in filter clauses come exclusively from PROP_ALLOWED_FILTER_KEYS (a static
frozenset), not from user input — this is the structural injection prevention layer.
Column names in SELECT come exclusively from PROP_COLUMN_MAP (a static dict) keyed by
prop_type Literal — prop_type is validated by Pydantic before build() is ever called.

No f-string SQL for user data. No string interpolation of user values. Period.
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
    SUM(CASE WHEN {col} >= $3 THEN 1 ELSE 0 END) AS successes,
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

        return sql, tuple(args)
