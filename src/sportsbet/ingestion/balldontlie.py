"""Ball Don't Lie free NBA API client (no auth required, v1 tier).

Provides live NBA player and team stats for context enrichment in the
nba_context_producer pipeline. All functions are async, use httpx, and
return empty values on any failure so the pipeline degrades gracefully.

Base URL: https://www.balldontlie.io/api/v1
Rate limit: 60 requests/minute on free tier. Each function makes 1 request.

Functions:
    fetch_player_season_averages(player_id, season) → avg pts/reb/ast dict or None
    fetch_team_recent_games(team_id, season, n_games) → list of recent game dicts
    fetch_player_game_logs(player_id, season, n_games) → sorted list of stat dicts
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_BDL_BASE = "https://www.balldontlie.io/api/v1"


async def fetch_player_season_averages(
    player_id: int,
    season: int,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Fetch NBA season averages for a player from Ball Don't Lie.

    Args:
        player_id: Ball Don't Lie player ID (integer).
        season: NBA season start year (e.g. 2024 for 2024-25).
        timeout: HTTP timeout in seconds.

    Returns:
        Dict with fields like pts, reb, ast, stl, blk, fg3m, min, or None if not found.
    """
    url = f"{_BDL_BASE}/season_averages"
    params: dict[str, Any] = {"season": season, "player_ids[]": player_id}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except Exception as exc:
        log.warning("balldontlie_averages_failed", player_id=player_id, error_type=type(exc).__name__)
        return None

    results: list[dict[str, Any]] = data.get("data", [])
    return results[0] if results else None


async def fetch_team_recent_games(
    team_id: int,
    season: int = 2024,
    n_games: int = 10,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Fetch recent games for an NBA team from Ball Don't Lie.

    Useful for computing team-level pace or defensive stats when
    the local DB has no entries for the current season yet.

    Args:
        team_id: Ball Don't Lie team ID (integer).
        season: NBA season start year.
        n_games: Max number of recent games to return.
        timeout: HTTP timeout in seconds.

    Returns:
        List of game dicts (date, home_team_score, visitor_team_score, etc.).
        Sorted newest-first. Empty on failure or no games found.
    """
    url = f"{_BDL_BASE}/games"
    params: dict[str, Any] = {
        "team_ids[]": team_id,
        "seasons[]": season,
        "per_page": n_games,
        "page": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except Exception as exc:
        log.warning("balldontlie_games_failed", team_id=team_id, error_type=type(exc).__name__)
        return []

    results: list[dict[str, Any]] = data.get("data", [])
    results.sort(key=lambda g: g.get("date", ""), reverse=True)
    return results


async def fetch_player_game_logs(
    player_id: int,
    season: int = 2024,
    n_games: int = 10,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Fetch recent per-game stats for an NBA player from Ball Don't Lie.

    Args:
        player_id: Ball Don't Lie player ID.
        season: NBA season start year.
        n_games: Number of most-recent games to return.
        timeout: HTTP timeout in seconds.

    Returns:
        List of stat dicts (pts, reb, ast, stl, blk, min, game metadata).
        Sorted newest-first. Empty on failure.
    """
    url = f"{_BDL_BASE}/stats"
    params: dict[str, Any] = {
        "player_ids[]": player_id,
        "seasons[]": season,
        "per_page": n_games,
        "page": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except Exception as exc:
        log.warning("balldontlie_stats_failed", player_id=player_id, error_type=type(exc).__name__)
        return []

    results: list[dict[str, Any]] = data.get("data", [])
    results.sort(key=lambda g: g.get("game", {}).get("date", ""), reverse=True)
    return results
