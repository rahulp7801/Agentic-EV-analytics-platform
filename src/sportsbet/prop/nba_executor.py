"""NBA prop executor: run_nba_prop_query async function with NormalDist probability model.

Data model:
    nba_player_stats stores season TOTALS (one row per player per season). There are
    NO per-game frequency rows available. Probability is derived via normal approximation:
        avg_per_game = total_stat / games_played  (from AVG() in SQL)
        std          = max(0.5, avg_per_game * CV_MAP[prop_type])  (floor prevents sigma=0)
        P(OVER line) = 1 - NormalDist(avg_per_game, std).cdf(line)

    This is fundamentally different from the NFL PropQueryBuilder (which uses frequency
    counts: SUM(CASE WHEN stat >= line) / COUNT(*)) because NBA season data cannot produce
    per-game binary outcomes.

MIN_SAMPLE_GAMES = 20:
    Games threshold for NBA (not weeks like NFL's MIN_PROP_SAMPLE_SIZE=30). Queries
    returning fewer than 20 total games are statistically unreliable for normal approx.
    Returns PropResult(data_source="insufficient_sample", true_probability=None).

Decimal wrapping rule:
    ALL floats must be wrapped with Decimal(str(round(x, 6))) before PropResult
    assignment. PropResult.model_config = strict=True rejects raw float values.
    NEVER assign float directly to a Decimal field — Pydantic strict=True will raise.

std floor:
    max(0.5, std) prevents StatisticsError when avg_per_game = 0.0 (e.g. assists for
    a center). NormalDist(0, 0) raises StatisticsError: sigma must be positive.

Wilson CI:
    NOT used here — Wilson CI requires discrete success/failure counts. Season-aggregate
    data cannot produce per-game binary outcomes, so confidence_interval=None. This is
    documented as a known limitation of the v1 NBA probability model.

Double-double:
    Uses inclusion-exclusion P(at least two categories >= 10):
        P = P(pts)*P(reb) + P(pts)*P(ast) + P(reb)*P(ast) - 2*P(pts)*P(reb)*P(ast)
    Independence assumption — documented as v1 heuristic.

Placeholder constants for Plan 02 NBAQuantAgent:
    LEAGUE_AVG_PACE, LEAGUE_AVG_DEF_RATING, REST_PENALTY, HOME_BOOST — exported here
    so Plan 02 can import them without modifying this module.
"""
from __future__ import annotations

import math
from decimal import Decimal
from statistics import NormalDist

import asyncpg
import structlog
from statsmodels.stats.proportion import proportion_confint

from sportsbet.graph.models import PropParams, PropResult
from sportsbet.prop.nba_query_builder import NBA_PROP_CV_MAP, NBAQueryBuilder

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_SAMPLE_GAMES: int = 20

# Plan 02 NBAQuantAgent adjustment factors — defined here for import stability
LEAGUE_AVG_PACE: Decimal = Decimal("100.0")
LEAGUE_AVG_DEF_RATING: Decimal = Decimal("115.0")
REST_PENALTY: Decimal = Decimal("0.03")
HOME_BOOST: Decimal = Decimal("0.015")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm_cdf_over(avg: float, std: float, line: float) -> float:
    """P(stat > line) using normal distribution CDF.

    P(OVER line) = 1 - P(stat <= line) = 1 - NormalDist(avg, std).cdf(line)

    std floor of max(0.5, std) prevents StatisticsError when avg=0.0.
    The 0.5 floor ensures sigma is always positive per NormalDist requirements.
    """
    safe_std = max(0.5, std)
    return 1.0 - NormalDist(mu=avg, sigma=safe_std).cdf(line)


def _double_double_prob(avg_pts: float, avg_reb: float, avg_ast: float) -> float:
    """P(double-double) via inclusion-exclusion over three categories.

    Inclusion-exclusion: P(at least two categories >= 10)
        P = P(pts>=10)*P(reb>=10) + P(pts>=10)*P(ast>=10) + P(reb>=10)*P(ast>=10)
            - 2 * P(pts>=10)*P(reb>=10)*P(ast>=10)

    Independence assumption — documented as v1 heuristic. Correlation between
    point-rebound-assist outcomes is not modeled in v1.
    """
    std_pts = max(0.5, avg_pts * float(NBA_PROP_CV_MAP["points"]))
    std_reb = max(0.5, avg_reb * float(NBA_PROP_CV_MAP["rebounds"]))
    std_ast = max(0.5, avg_ast * float(NBA_PROP_CV_MAP["assists"]))

    p_pts = _norm_cdf_over(avg_pts, std_pts, 10.0)
    p_reb = _norm_cdf_over(avg_reb, std_reb, 10.0)
    p_ast = _norm_cdf_over(avg_ast, std_ast, 10.0)

    return p_pts * p_reb + p_pts * p_ast + p_reb * p_ast - 2 * p_pts * p_reb * p_ast


# ---------------------------------------------------------------------------
# Phase 18: NBA gamelog binary frequency executor (conditional path)
# ---------------------------------------------------------------------------

MIN_CONDITIONAL_SAMPLE: int = 1  # at least 1 game needed (zero handled as edge case)


async def run_nba_gamelog_query(pool: asyncpg.Pool, params: PropParams) -> PropResult:
    """Execute a conditional nba_player_gamelogs query using Wilson CI (binary frequency).

    Called by run_nba_prop_query when any situational filter is set. Uses per-game
    binary outcome counts (total, successes) rather than season-aggregate NormalDist.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    params:
        Fully validated PropParams with at least one situational filter set.

    Returns
    -------
    PropResult
        - data_source="insufficient_sample" when total=0 (no games match filters)
        - data_source="conditional_small_sample" when total < 30 (wide Wilson CI)
        - data_source="postgresql" when total >= 30 (reliable frequency estimate)

    Notes
    -----
    Wilson CI is appropriate here because gamelogs provide per-game binary outcomes
    (stat >= line: True/False) — unlike season-aggregate data used by the NormalDist path.
    """
    sql, args = NBAQueryBuilder.build(params)

    log.info(
        "nba_gamelog_query_executing",
        prop_type=params.prop_type,
        player_id=params.player_id,
        season=params.season,
        opponent_team=params.opponent_team,
        home_away=params.home_away,
        last_n_games=params.last_n_games,
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)

    total: int = int(row["total"]) if row and row["total"] is not None else 0
    successes: int = int(row["successes"]) if row and row["successes"] is not None else 0

    # Guard zero — Wilson CI returns NaN for nobs=0
    if total == 0:
        log.warning(
            "nba_gamelog_insufficient_sample",
            total=total,
            prop_type=params.prop_type,
        )
        return PropResult(
            data_source="insufficient_sample",
            sample_size=0,
        )

    lo: float
    hi: float
    lo, hi = proportion_confint(count=successes, nobs=total, alpha=0.05, method="wilson")

    # Belt-and-suspenders NaN guard
    if math.isnan(lo) or math.isnan(hi):
        log.warning(
            "nba_gamelog_wilson_ci_nan",
            total=total,
            successes=successes,
            prop_type=params.prop_type,
        )
        return PropResult(
            data_source="insufficient_sample",
            sample_size=total,
        )

    true_prob = Decimal(str(round(successes / total, 6)))
    ci: tuple[Decimal, Decimal] = (
        Decimal(str(round(lo, 6))),
        Decimal(str(round(hi, 6))),
    )

    mean_stat: Decimal | None = None
    if row and row["mean_val"] is not None:
        mean_stat = Decimal(str(round(float(row["mean_val"]), 2)))

    # Tag conditional small samples distinctly
    data_src: str = "conditional_small_sample" if total < 30 else "postgresql"

    log.info(
        "nba_gamelog_result_computed",
        true_probability=str(true_prob),
        sample_size=total,
        ci_lo=str(ci[0]),
        ci_hi=str(ci[1]),
        data_source=data_src,
    )

    return PropResult(
        true_probability=true_prob,
        sample_size=total,
        confidence_interval=ci,
        data_source=data_src,
        mean_stat=mean_stat,
    )


# ---------------------------------------------------------------------------
# Public async executor
# ---------------------------------------------------------------------------


async def run_nba_prop_query(pool: asyncpg.Pool, params: PropParams) -> PropResult:
    """Execute a parameterized nba_player_stats query and return a PropResult.

    Calls NBAQueryBuilder.build(params) to obtain the SQL + args, then acquires
    a connection from the pool and runs fetchrow. For most prop types, the row
    contains total_games, total_stat, and avg_per_game. For double_double, the
    row contains total_games, avg_pts, avg_reb, avg_ast.

    Parameters
    ----------
    pool:
        asyncpg connection pool (created via create_async_pool).
    params:
        Fully validated PropParams — must have passed Pydantic validation before
        this function is called.

    Returns
    -------
    PropResult
        - data_source="insufficient_sample", true_probability=None when total_games < MIN_SAMPLE_GAMES
        - data_source="postgresql", Decimal true_probability (clamped to [0.01, 0.99]) otherwise

    Notes
    -----
    confidence_interval is always None for NBA props — Wilson CI requires per-game
    binary outcome counts which are not available in season-aggregate data.
    true_probability is clamped to [0.01, 0.99] to prevent extreme probability
    outputs from propagating to Kelly Criterion sizing.

    Phase 18: conditional dispatch to run_nba_gamelog_query when any situational
    filter is set. The gamelog path uses Wilson CI (binary frequency) instead of
    NormalDist CDF. Season-aggregate path preserved for unconditional queries.
    """
    # Phase 18 SC-5: route conditional queries to gamelog binary frequency path
    is_conditional = bool(
        params.last_n_games is not None
        or params.teammate_out
        or params.opponent_team is not None
        or params.home_away is not None
    )
    if is_conditional:
        return await run_nba_gamelog_query(pool, params)

    sql, args = NBAQueryBuilder.build(params)

    log.info(
        "nba_prop_query_executing",
        prop_type=params.prop_type,
        player_id=params.player_id,
        season=params.season,
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)

    total_games: int = int(row["total_games"]) if row and row["total_games"] else 0

    if total_games < MIN_SAMPLE_GAMES:
        log.warning(
            "nba_prop_insufficient_sample",
            total_games=total_games,
            min_required=MIN_SAMPLE_GAMES,
            prop_type=params.prop_type,
        )
        return PropResult(
            data_source="insufficient_sample",
            sample_size=total_games,
        )

    # --- Double-double: inclusion-exclusion over three component averages ---
    if params.prop_type == "double_double":
        avg_pts = float(row["avg_pts"] or 0.0)
        avg_reb = float(row["avg_reb"] or 0.0)
        avg_ast = float(row["avg_ast"] or 0.0)

        p_dd = _double_double_prob(avg_pts, avg_reb, avg_ast)
        true_prob = Decimal(str(round(p_dd, 6)))
        true_prob = max(Decimal("0.01"), min(Decimal("0.99"), true_prob))

        log.info(
            "nba_double_double_result",
            true_probability=str(true_prob),
            sample_size=total_games,
            avg_pts=avg_pts,
            avg_reb=avg_reb,
            avg_ast=avg_ast,
        )

        return PropResult(
            true_probability=true_prob,
            sample_size=total_games,
            data_source="postgresql",
            mean_stat=None,  # composite prop — no single mean_stat
        )

    # --- Single-stat and PRA: NormalDist CDF over avg_per_game ---
    avg_per_game: float = float(row["avg_per_game"] or 0.0)
    cv: Decimal = NBA_PROP_CV_MAP[params.prop_type]
    std: float = max(0.5, avg_per_game * float(cv))

    p_over: float = _norm_cdf_over(avg_per_game, std, float(params.line))
    true_prob = Decimal(str(round(p_over, 6)))
    true_prob = max(Decimal("0.01"), min(Decimal("0.99"), true_prob))

    mean_stat = Decimal(str(round(avg_per_game, 2)))

    log.info(
        "nba_prop_result_computed",
        true_probability=str(true_prob),
        sample_size=total_games,
        avg_per_game=avg_per_game,
        mean_stat=str(mean_stat),
    )

    return PropResult(
        true_probability=true_prob,
        sample_size=total_games,
        data_source="postgresql",
        mean_stat=mean_stat,
    )
