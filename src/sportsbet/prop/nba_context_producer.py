"""NBA context signals producer for LangGraph NBA prop pipeline.

make_nba_context_signals_producer(pool, target_date=None) returns an async
callable compatible with the LangGraph node interface. The returned node reads
nba_player_gamelogs to compute rest_days and home/away, then writes
NBAContextSignals into GraphState before make_nba_quant_agent runs.

Purpose: INT-3 gap closure. nba_context_signals is always None in automated
runs because no pipeline node sets it. The four-stage adjustment in
_apply_nba_context_adjustments (pace, def_rating, rest, home) is fully
implemented but receives context=None and returns immediately. This producer
feeds it game-log context. Defense and pace remain neutral constants until
actual point-in-time team metrics are available.

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
"""
from __future__ import annotations

import structlog
from datetime import date as date_cls
from typing import Any, Callable, Coroutine, Optional

import asyncpg

from sportsbet.graph.models import NBAContextSignals
from sportsbet.prop.nba_executor import LEAGUE_AVG_DEF_RATING, LEAGUE_AVG_PACE

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# SQL: most recent gamelog entry for player before the target game date.
# Filtering by game_date < $2 (target date) instead of season = $2 avoids
# season-numbering mismatches (2025 label vs 2026 label for the same NBA season)
# and guarantees we always get the true last game played before this matchup.
_SQL_LAST_GAME = """
    SELECT team_abbreviation, game_date
    FROM nba_player_gamelogs
    WHERE player_id = $1
      AND game_date < $2
    ORDER BY game_date DESC
    LIMIT 1
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
        today: date_cls = state.get("as_of_date") or target_date or date_cls.today()

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
            # 2a. Most recent gamelog before target game date (not filtered by season —
            # avoids season-numbering mismatches; game_date cutoff is more reliable)
            gamelog_row = await conn.fetchrow(_SQL_LAST_GAME, player_id, today)

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

        # --- 4. Build signals ---
        signals = NBAContextSignals(
            # Opponent points scored is not points allowed per possession.
            # Keep neutral until timestamped team defense/pace data is ingested;
            # season totals would also leak future games into historical scans.
            opponent_def_rating=LEAGUE_AVG_DEF_RATING,
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
