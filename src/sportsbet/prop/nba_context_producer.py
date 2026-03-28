"""NBA context signals producer for LangGraph NBA prop pipeline.

make_nba_context_signals_producer(pool, target_date=None) returns an async
callable compatible with the LangGraph node interface. The returned node reads
nba_player_gamelogs to compute rest_days and opponent_def_rating, then writes
NBAContextSignals into GraphState before make_nba_quant_agent runs.

Purpose: INT-3 gap closure. nba_context_signals is always None in automated
runs because no pipeline node sets it. The four-stage adjustment in
_apply_nba_context_adjustments (pace, def_rating, rest, home) is fully
implemented but receives context=None and returns immediately. This producer
feeds it real data.

Design decisions (Phase 20 locked):
- Module-level imports for patchability (Phase 8 pattern)
- Do NOT guard NBAContextSignals import with TYPE_CHECKING — LangGraph
  get_type_hints() must resolve it at runtime (Phase 12 locked decision)
- MagicMock pool pattern in tests (Phase 4 locked decision)
- player_id_raw cast to int() before asyncpg query — prevents DataError on INTEGER column
- rest_days formula: max(0, (today - last_game_date).days - 1)
  Yesterday (1 day ago) = 0 rest days (back-to-back)
- opponent_def_rating = LEAGUE_AVG_DEF_RATING * (avg_pts / LEAGUE_AVG_PTS_PER_PLAYER)
  clamped to [90, 140], wrapped as Decimal
- pace_factor = LEAGUE_AVG_PACE (neutral; no possession data in v1 schema)

SQL queries:
- nba_player_gamelogs: get team_abbreviation + last game_date for player/season
- nba_player_stats: get avg_pts_per_game for opponent's scoring proxy
"""
from __future__ import annotations

import structlog
from datetime import date as date_cls
from decimal import Decimal
from typing import Any, Callable, Coroutine, Optional

import asyncpg

from sportsbet.graph.models import NBAContextSignals
from sportsbet.prop.nba_executor import LEAGUE_AVG_DEF_RATING, LEAGUE_AVG_PACE

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

LEAGUE_AVG_PTS_PER_PLAYER: float = 8.0

# SQL: most recent gamelog entry for player/season
_SQL_LAST_GAME = """
    SELECT team_abbreviation, game_date
    FROM nba_player_gamelogs
    WHERE player_id = $1
      AND season = $2
    ORDER BY game_date DESC
    LIMIT 1
"""

# SQL: opponent scoring proxy from nba_player_stats (season aggregate)
# avg_pts_per_game approximates defensive rating via points allowed per player
_SQL_OPP_DEF = """
    SELECT AVG(CAST(points AS FLOAT) / NULLIF(games_played, 0)) AS avg_pts_per_game
    FROM nba_player_stats
    WHERE team_abbreviation = $1
      AND season = $2
"""

# ---------------------------------------------------------------------------
# League-average fallback
# ---------------------------------------------------------------------------


def _league_avg_signals(is_home: bool = False) -> dict[str, Any]:
    """Return NBAContextSignals with league-average defaults.

    Used when:
    - player_id is empty/invalid (no DB query)
    - No gamelog rows found for player/season (cold DB)
    """
    return {
        "nba_context_signals": NBAContextSignals(
            opponent_def_rating=LEAGUE_AVG_DEF_RATING,
            pace_factor=LEAGUE_AVG_PACE,
            rest_days=1,
            is_home=is_home,
        )
    }


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def make_nba_context_signals_producer(
    pool: asyncpg.Pool,
    target_date: Optional[date_cls] = None,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]:
    """Return an async LangGraph node that populates nba_context_signals in GraphState.

    Parameters
    ----------
    pool:
        asyncpg connection pool injected at graph construction time.
    target_date:
        The game date to compute rest_days against. Defaults to date.today()
        when None. Provide explicitly in tests to avoid date-dependent behavior.

    Returns
    -------
    async callable
        Accepts a GraphState-like dict, returns partial state dict with
        {"nba_context_signals": NBAContextSignals | None}.

    LangGraph compatibility:
        The returned coroutine accepts the full state dict and returns a partial
        dict — LangGraph merges it via reducers (Phase 2 locked pattern).
    """

    async def producer(state: dict[str, Any]) -> dict[str, Any]:
        today: date_cls = target_date or date_cls.today()

        # --- 1. Validate player_id ---
        player_id_raw: str = state.get("receiver_gsis_id", "")
        if not player_id_raw:
            log.debug("nba_context_producer_empty_player_id")
            return _league_avg_signals(is_home=False)

        try:
            player_id: int = int(player_id_raw)
        except (ValueError, TypeError):
            log.warning(
                "nba_context_producer_invalid_player_id",
                player_id_raw=player_id_raw,
            )
            return {"nba_context_signals": None}

        season: int = state.get("season", 2024)
        home_team: str = state.get("home_team", "")
        away_team: str = state.get("away_team", "")

        # --- 2. Query DB ---
        async with pool.acquire() as conn:
            # 2a. Most recent gamelog for player/season
            gamelog_row = await conn.fetchrow(_SQL_LAST_GAME, player_id, season)

            if gamelog_row is None:
                log.info(
                    "nba_context_producer_no_gamelogs",
                    player_id=player_id,
                    season=season,
                )
                return _league_avg_signals(is_home=False)

            team_abbr: str = gamelog_row["team_abbreviation"]
            last_game_date: date_cls = gamelog_row["game_date"]

            # 2b. Compute rest_days: max(0, days_since - 1)
            # Yesterday = 1 day since game = 0 rest days (back-to-back)
            rest_days: int = max(0, (today - last_game_date).days - 1)

            # 2c. is_home from GraphState home_team comparison — no extra DB query
            is_home: bool = team_abbr == home_team
            opponent_abbr: str = away_team if is_home else home_team

            # 2d. Opponent defensive rating proxy from nba_player_stats
            opp_row = await conn.fetchrow(_SQL_OPP_DEF, opponent_abbr, season)

        # --- 3. Compute opponent_def_rating ---
        avg_pts_raw = opp_row["avg_pts_per_game"] if opp_row is not None else None
        if avg_pts_raw is None:
            # Fall back to league average when no opponent stats
            normalized = LEAGUE_AVG_DEF_RATING
        else:
            avg_pts: float = float(avg_pts_raw)
            ratio: float = avg_pts / LEAGUE_AVG_PTS_PER_PLAYER
            normalized = LEAGUE_AVG_DEF_RATING * Decimal(str(round(ratio, 6)))
            # Clamp to [90, 140]
            normalized = max(Decimal("90"), min(Decimal("140"), normalized))

        # --- 4. Build signals ---
        signals = NBAContextSignals(
            opponent_def_rating=normalized,
            pace_factor=LEAGUE_AVG_PACE,
            rest_days=rest_days,
            is_home=is_home,
        )

        log.info(
            "nba_context_signals_producer_complete",
            player_id=player_id,
            season=season,
            team_abbr=team_abbr,
            rest_days=rest_days,
            is_home=is_home,
            opponent_abbr=opponent_abbr,
            opponent_def_rating=str(signals.opponent_def_rating),
        )

        return {"nba_context_signals": signals}

    return producer
