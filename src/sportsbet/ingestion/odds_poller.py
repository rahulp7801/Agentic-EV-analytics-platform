"""Odds API poller with budget manager and staleness guard.

Implements OddsAPIPoller (async context manager) for fetching NFL odds from
The Odds API, BudgetExhaustedError for credit-cap enforcement, and is_stale()
for staleness checking before odds reach the Arbitrage Agent.

Budget persistence: _credits_remaining is in-memory only in v1. Counter resets
on process restart — a WARNING is logged on first __aenter__ so operators are
aware. Persistent budget tracking is deferred to Phase 5 per RESEARCH.md open
question #3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

ODDS_API_BASE = "https://api.the-odds-api.com"
NFL_SPORT_KEY = "americanfootball_nfl"
DEFAULT_STALENESS_MINUTES = 5


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BudgetExhaustedError(RuntimeError):
    """Raised when Odds API daily credit cap is reached or credits_remaining < 1."""


# ---------------------------------------------------------------------------
# Staleness guard
# ---------------------------------------------------------------------------


def is_stale(
    snapped_at: datetime,
    threshold_minutes: int = DEFAULT_STALENESS_MINUTES,
) -> bool:
    """Return True if snapped_at is older than threshold_minutes, else False.

    Args:
        snapped_at: Timezone-aware UTC datetime of the odds snapshot.
        threshold_minutes: Maximum acceptable age in minutes. Defaults to 5.

    Returns:
        True when stale (age > threshold), False when fresh.

    Raises:
        TypeError: If snapped_at is a naive datetime (no tzinfo).
    """
    now = datetime.now(timezone.utc)
    if snapped_at.tzinfo is None:
        raise TypeError(
            "snapped_at must be timezone-aware; got naive datetime. "
            "Use datetime.now(timezone.utc) or attach tzinfo=timezone.utc."
        )
    age_minutes = (now - snapped_at).total_seconds() / 60.0
    return age_minutes > threshold_minutes


# ---------------------------------------------------------------------------
# OddsAPIPoller
# ---------------------------------------------------------------------------


class OddsAPIPoller:
    """Async context manager that polls The Odds API for NFL odds.

    Usage:
        async with OddsAPIPoller(api_key="...", daily_credit_cap=500) as poller:
            odds = await poller.fetch_nfl_odds()

    Budget guard: if _credits_remaining is not None and < 1, fetch_nfl_odds()
    raises BudgetExhaustedError without making any HTTP request.

    Credit tracking: _credits_remaining is updated from the x-requests-remaining
    response header after each successful fetch. It starts as None (unknown)
    until the first successful response.
    """

    def __init__(self, api_key: str, daily_credit_cap: int) -> None:
        self._api_key = api_key
        self._daily_credit_cap = daily_credit_cap
        self._credits_remaining: int | None = None
        self._client: httpx.AsyncClient | None = None
        self._client_cm: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OddsAPIPoller":
        if self._credits_remaining is None:
            log.warning(
                "odds_budget_counter_reset",
                note="in-memory only; restarts reset counter",
            )
        # Enter httpx.AsyncClient as context manager so mock patches work correctly.
        # self._client_cm is the context manager object; self._client is the active client.
        self._client_cm = httpx.AsyncClient(base_url=ODDS_API_BASE, timeout=10.0)
        self._client = await self._client_cm.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self._client_cm is not None:
            await self._client_cm.__aexit__(exc_type, exc_val, exc_tb)
            self._client_cm = None
            self._client = None

    async def fetch_nfl_odds(
        self,
        regions: str = "us",
        markets: str = "h2h,spreads,totals",
    ) -> list[dict]:  # type: ignore[type-arg]
        """Fetch current NFL odds from The Odds API.

        Raises:
            BudgetExhaustedError: If _credits_remaining is not None and < 1.
                No HTTP call is made in this case.
            httpx.HTTPStatusError: If the API returns a non-2xx status.

        Returns:
            Parsed JSON list of event dicts from the Odds API.
        """
        if self._credits_remaining is not None and self._credits_remaining < 1:
            raise BudgetExhaustedError(
                f"Odds API daily credit cap reached. "
                f"credits_remaining={self._credits_remaining}, "
                f"daily_credit_cap={self._daily_credit_cap}"
            )

        assert self._client is not None, "fetch_nfl_odds called outside async context manager"

        response = await self._client.get(
            f"/v4/sports/{NFL_SPORT_KEY}/odds",
            params={
                "apiKey": self._api_key,
                "regions": regions,
                "markets": markets,
            },
        )
        response.raise_for_status()

        self._credits_remaining = int(
            response.headers.get("x-requests-remaining", "0")
        )

        log.info(
            "odds_api_fetched",
            credits_remaining=self._credits_remaining,
            sport_key=NFL_SPORT_KEY,
        )

        return response.json()  # type: ignore[no-any-return]
