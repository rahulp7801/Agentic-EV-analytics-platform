"""QueryBuilder: static SQL template dispatch with FilterKey guard.

Security invariant: user-supplied data (posteam, season, filter values) NEVER
appears in the SQL string. All values are passed as positional asyncpg $N params.
Column names in filter clauses come exclusively from ALLOWED_FILTER_KEYS (a static
frozenset), not from user input — this is the structural injection prevention layer.

No f-string SQL. No string interpolation of user data. Period.
"""
from __future__ import annotations

import structlog

from sportsbet.graph.models import QuantParams

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Allowed filter column names (allowlist — NOT derived from user input)
# ---------------------------------------------------------------------------

ALLOWED_FILTER_KEYS: frozenset[str] = frozenset({"down", "ydstogo", "defteam", "game_id", "week"})

# ---------------------------------------------------------------------------
# Static SQL templates
# Each template uses $1=posteam, $2=season as base positional params.
# Additional filters are appended as $3, $4, ... by build().
# ---------------------------------------------------------------------------

_PASSING_TEMPLATE = """
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN pass_touchdown = 1 OR (air_yards IS NOT NULL AND air_yards > 0) THEN 1 ELSE 0 END) AS successes
FROM play_by_play
WHERE posteam = $1
  AND season >= $2
  AND play_type = 'pass'
  AND two_point_attempt = 0
"""

_RUSHING_TEMPLATE = """
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN rush_touchdown = 1 OR yards_gained >= 4 THEN 1 ELSE 0 END) AS successes
FROM play_by_play
WHERE posteam = $1
  AND season >= $2
  AND play_type = 'run'
  AND two_point_attempt = 0
"""

_RECEIVING_TEMPLATE = """
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN complete_pass = 1 THEN 1 ELSE 0 END) AS successes
FROM play_by_play
WHERE posteam = $1
  AND season >= $2
  AND play_type = 'pass'
  AND two_point_attempt = 0
"""

_QUERY_TEMPLATES: dict[str, str] = {
    "passing": _PASSING_TEMPLATE,
    "rushing": _RUSHING_TEMPLATE,
    "receiving": _RECEIVING_TEMPLATE,
}


class QueryBuilder:
    """Builds parameterized asyncpg SQL queries from validated QuantParams.

    The build() classmethod is the sole public API. It:
    1. Selects the appropriate static template by stat_type (Literal — already validated).
    2. Appends allowed filter clauses using column names from ALLOWED_FILTER_KEYS only.
    3. Returns (sql_string, args_tuple) where args_tuple contains all $N values.

    User-supplied values (posteam, season, filter values) are ALWAYS in args_tuple,
    never interpolated into the SQL string.
    """

    @classmethod
    def build(cls, params: QuantParams) -> tuple[str, tuple[object, ...]]:
        """Build a parameterized SQL query for the given QuantParams.

        Parameters
        ----------
        params:
            A fully validated QuantParams instance (Pydantic ensures Literal stat_type,
            season range, etc. are already correct before build() is called).

        Returns
        -------
        tuple[str, tuple[object, ...]]
            (sql_string, args_tuple) where sql_string contains only $N placeholders
            for user values. Pass to asyncpg as: await conn.fetchrow(sql, *args).
        """
        # Base template selected by stat_type (Literal — validated by Pydantic)
        sql: str = _QUERY_TEMPLATES[params.stat_type]

        # Base positional args: $1=posteam, $2=season
        args: list[object] = [params.posteam, params.season]

        # FilterKey guard: only ALLOWED_FILTER_KEYS pass through
        # Column names come from the allowlist (not user input) — safe for SQL concatenation.
        # Values always go into positional args — never interpolated.
        next_idx = 3
        for key, value in params.filters.items():
            if key not in ALLOWED_FILTER_KEYS:
                log.warning("unknown_filter_key_dropped", key=key)
                continue
            # key is from ALLOWED_FILTER_KEYS (static set) — not user data
            sql = sql + f"  AND {key} = ${next_idx}\n"
            args.append(value)
            next_idx += 1

        return sql, tuple(args)
