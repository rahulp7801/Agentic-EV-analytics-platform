"""NBA context signals producer for LangGraph NBA prop pipeline.

make_nba_context_signals_producer(pool, target_date=None) returns an async
callable compatible with the LangGraph node interface. The returned node reads
nba_player_gamelogs to compute rest_days and home/away, then writes
NBAContextSignals into GraphState before make_nba_quant_agent runs.

The scheduled scanner wires this node before the NBA quant agent. Matchup context
is emitted only when the player's latest pregame team belongs to the scheduled
event. Missing or conflicting identity produces no context, so the quant agent
cannot invent the player's side or opponent. Defense and pace remain neutral
constants until actual point-in-time team metrics are available.

Design decisions (Phase 20 locked):
- Module-level imports for patchability (Phase 8 pattern)
- Do NOT guard NBAContextSignals import with TYPE_CHECKING — LangGraph
  get_type_hints() must resolve it at runtime (Phase 12 locked decision)
- MagicMock pool pattern in tests (Phase 4 locked decision)
- player_id_raw cast to int() before asyncpg query — prevents DataError on INTEGER column
- rest_days formula: max(0, (today - last_game_date).days - 1)
  Yesterday (1 day ago) = 0 rest days (back-to-back)
- opponent_def_rating = LEAGUE_AVG_DEF_RATING until timestamped team defense is available
- pace_factor = LEAGUE_AVG_PACE (neutral; no possession data in v1 schema)

SQL queries:
- nba_player_gamelogs: get team_abbreviation + last game_date for player/season
"""
from __future__ import annotations

import structlog
from datetime import date as date_cls
from typing import Any, Callable, Coroutine, Optional

import asyncpg
from nba_api.stats.static.teams import get_teams

from sportsbet.graph.models import NBAContextSignals
from sportsbet.prop.nba_executor import LEAGUE_AVG_DEF_RATING, LEAGUE_AVG_PACE

log = structlog.get_logger()

_NBA_TEAM_NAMES={team['full_name']:team['abbreviation'] for team in get_teams()}
_NBA_TEAM_ABBREVIATIONS=frozenset(_NBA_TEAM_NAMES.values())


def nba_team_abbreviation(value: object) -> str:
    """Resolve an exact NBA full name or canonical abbreviation."""
    if not isinstance(value,str):
        raise ValueError('Unknown NBA team identity')
    abbreviation=_NBA_TEAM_NAMES.get(value,value if value in _NBA_TEAM_ABBREVIATIONS else None)
    if abbreviation is None:
        raise ValueError('Unknown NBA team identity')
    return abbreviation

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
        raw_home=state.get("home_team")
        raw_away=state.get("away_team")
        if bool(raw_home) != bool(raw_away):
            raise ValueError('Incomplete NBA team identity')
        if raw_home and raw_away:
            home_team=nba_team_abbreviation(raw_home)
            away_team=nba_team_abbreviation(raw_away)
            normalized_teams={"home_team":home_team,"away_team":away_team}
        else:
            home_team=away_team=""
            normalized_teams={}

        # --- 1. Validate player_id ---
        player_id_raw: str = state.get("receiver_gsis_id", "")
        if not player_id_raw:
            log.debug("nba_context_producer_empty_player_id")
            return {"nba_context_signals": None} | normalized_teams

        try:
            player_id: int = int(player_id_raw)
        except (ValueError, TypeError):
            log.warning(
                "nba_context_producer_invalid_player_id",
                player_id_raw=player_id_raw,
            )
            return {"nba_context_signals": None} | normalized_teams

        season: int = state.get("season", 2024)
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
                return {"nba_context_signals": None} | normalized_teams

            team_abbr: str = gamelog_row["team_abbreviation"]
            last_game_date: date_cls = gamelog_row["game_date"]

            if team_abbr not in (home_team,away_team):
                log.warning("nba_context_producer_team_not_in_event",player_id=player_id,
                    team_abbr=team_abbr)
                return {"nba_context_signals": None} | normalized_teams

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

        return {"nba_context_signals": signals} | normalized_teams

    return producer
