"""Quant executor: run_quant_query async function + Wilson CI computation.

Security chain:
  QuantParams (Pydantic validated) -> QueryBuilder.build() -> asyncpg $N params

MIN_SAMPLE_SIZE gate: queries returning fewer than 30 rows are statistically
unreliable. The gate returns QuantResult(data_source="insufficient_sample")
rather than a probability — callers must handle the None true_probability case.

Wilson CI: proportion_confint(method="wilson") from statsmodels. Bounds are
converted to Decimal(str(round(x, 6))) before being passed to QuantResult —
the strict=True Pydantic model rejects raw float values.

Pitfall guards (from RESEARCH.md):
- Pitfall 1: asyncpg args are Python int, not str — season/week from QuantParams
  are already int (Pydantic enforces int strict=True).
- Pitfall 3: CI bounds wrapped with Decimal(str(...)) — never assigned as float.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import asyncpg
import structlog
from statsmodels.stats.proportion import proportion_confint

from sportsbet.graph.models import QuantParams, QuantResult
from sportsbet.quant.query_builder import QueryBuilder

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

MIN_SAMPLE_SIZE: int = 30


async def run_quant_query(pool: asyncpg.Pool, params: QuantParams) -> QuantResult:
    """Execute a parameterized play_by_play aggregate query and return a QuantResult.

    Calls QueryBuilder.build(params) to obtain the SQL + args, then acquires a
    connection from the pool and runs fetchrow. The returned aggregate row has
    'total' (COUNT) and 'successes' (SUM CASE) columns.

    Parameters
    ----------
    pool:
        asyncpg connection pool (created via create_async_pool).
    params:
        Fully validated QuantParams — must have passed Pydantic validation before
        this function is called (enforced by make_quant_agent closure).

    Returns
    -------
    QuantResult
        - data_source="insufficient_sample", true_probability=None if total < MIN_SAMPLE_SIZE
        - data_source="postgresql",
        prediction_target="play_success", Decimal true_probability + tuple[Decimal,Decimal] CI otherwise

    Notes
    -----
    CI bounds use Decimal(str(round(x, 6))) to satisfy QuantResult.model_config strict=True.
    Raw float from scipy/statsmodels is NEVER assigned directly to a Decimal field.
    """
    sql, args = QueryBuilder.build(params)

    log.info(
        "quant_query_executing",
        stat_type=params.stat_type,
        posteam=params.posteam,
        season=params.season,
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)

    total: int = int(row["total"]) if row and row["total"] is not None else 0
    successes: int = int(row["successes"]) if row and row["successes"] is not None else 0

    if total < MIN_SAMPLE_SIZE:
        log.warning(
            "quant_insufficient_sample",
            total=total,
            min_required=MIN_SAMPLE_SIZE,
            stat_type=params.stat_type,
        )
        return QuantResult(
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

    log.info(
        "quant_result_computed",
        true_probability=str(true_prob),
        sample_size=total,
        ci_lo=str(ci[0]),
        ci_hi=str(ci[1]),
    )

    return QuantResult(
        true_probability=true_prob,
        sample_size=total,
        confidence_interval=ci,
        data_source="postgresql",
        prediction_target="play_success",
    )
