"""Prop executor: run_prop_query async function + Wilson CI computation.

Security chain:
  PropParams (Pydantic validated) -> PropQueryBuilder.build() -> asyncpg $N params

MIN_PROP_SAMPLE_SIZE gate: queries returning fewer than 30 rows are statistically
unreliable. The gate returns PropResult(data_source="insufficient_sample")
rather than a probability — callers must handle the None true_probability case
before applying Kelly Criterion sizing.

Wilson CI: proportion_confint(method="wilson") from statsmodels. Bounds are
converted to Decimal(str(round(x, 6))) before being passed to PropResult —
the strict=True Pydantic model rejects raw float values.

Pitfall guards (mirroring quant/executor.py patterns):
- asyncpg args use float(params.line) for line — avoids NUMERIC vs SMALLINT ambiguity.
- CI bounds wrapped with Decimal(str(...)) — never assigned as float.
- mean_val from AVG() may be None when no non-NULL rows exist — guarded explicitly.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import asyncpg
import structlog
from statsmodels.stats.proportion import proportion_confint

from sportsbet.graph.models import PropParams, PropResult
from sportsbet.prop.query_builder import PropQueryBuilder

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

MIN_PROP_SAMPLE_SIZE: int = 30


async def run_prop_query(pool: asyncpg.Pool, params: PropParams) -> PropResult:
    """Execute a parameterized player_stats aggregate query and return a PropResult.

    Calls PropQueryBuilder.build(params) to obtain the SQL + args, then acquires a
    connection from the pool and runs fetchrow. The returned aggregate row has
    'total' (COUNT), 'successes' (SUM CASE), and 'mean_val' (AVG) columns.

    Parameters
    ----------
    pool:
        asyncpg connection pool (created via create_async_pool).
    params:
        Fully validated PropParams — must have passed Pydantic validation before
        this function is called (enforced by make_prop_quant_agent closure).

    Returns
    -------
    PropResult
        - data_source="insufficient_sample", true_probability=None if total < MIN_PROP_SAMPLE_SIZE
        - data_source="postgresql", Decimal true_probability + tuple[Decimal,Decimal] CI + mean_stat otherwise

    Notes
    -----
    CI bounds use Decimal(str(round(x, 6))) to satisfy PropResult.model_config strict=True.
    Raw float from statsmodels is NEVER assigned directly to a Decimal field.
    mean_stat uses Decimal(str(round(float(row["mean_val"]), 2))) — 2 decimal places for display.
    mean_stat is None when row["mean_val"] is None (no non-NULL rows in player_stats).
    """
    sql, args = PropQueryBuilder.build(params)

    log.info(
        "prop_query_executing",
        prop_type=params.prop_type,
        player_id=params.player_id,
        season=params.season,
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)

    total: int = int(row["total"]) if row and row["total"] is not None else 0
    successes: int = int(row["successes"]) if row and row["successes"] is not None else 0

    if total < MIN_PROP_SAMPLE_SIZE:
        log.warning(
            "prop_insufficient_sample",
            total=total,
            min_required=MIN_PROP_SAMPLE_SIZE,
            prop_type=params.prop_type,
        )
        return PropResult(
            data_source="insufficient_sample",
            sample_size=total,
        )

    # Wilson CI — statsmodels proportion_confint with method="wilson"
    # bounds are float; convert to Decimal immediately (strict Pydantic guard)
    lo: float
    hi: float
    lo, hi = proportion_confint(count=successes, nobs=total, alpha=0.05, method="wilson")

    true_prob = Decimal(str(round(successes / total, 6)))
    ci: tuple[Decimal, Decimal] = (
        Decimal(str(round(lo, 6))),
        Decimal(str(round(hi, 6))),
    )

    # mean_val from AVG() — may be None if player_stats has no non-NULL rows for this column
    mean_stat: Decimal | None = None
    if row and row["mean_val"] is not None:
        mean_stat = Decimal(str(round(float(row["mean_val"]), 2)))

    log.info(
        "prop_result_computed",
        true_probability=str(true_prob),
        sample_size=total,
        ci_lo=str(ci[0]),
        ci_hi=str(ci[1]),
        mean_stat=str(mean_stat) if mean_stat is not None else "None",
    )

    return PropResult(
        true_probability=true_prob,
        sample_size=total,
        confidence_interval=ci,
        data_source="postgresql",
        mean_stat=mean_stat,
    )
